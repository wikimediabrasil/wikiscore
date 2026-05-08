import csv
import requests
from django.db import connection, models
from django.db.models import OuterRef, Subquery, F
from datetime import datetime, timezone as dt_timezone
from dateutil import parser
from urllib.parse import quote
from contests.models import Contest, Edit, Participant, ParticipantEnrollment, Qualification, Evaluation
from django.core.management.base import BaseCommand
from django.utils import timezone

WIKIMEDIA_API_HEADERS = {
    "User-Agent": "WikiScore/1.0 (https://github.com/WikiMovimentoBrasil/wikiscore; wikiscore@wmnobrasil.org)"
}

class Command(BaseCommand):
    help = "Carrega usuários inscritos no concurso."

    def add_arguments(self, parser):
        parser.add_argument('contest', type=str, help="Nome ID do concurso")

    def handle(self, *args, **options):
        contest_name_id = options.get('contest')
        contest = self.get_contest(contest_name_id)

        # Coleta planilha com usuários inscritos
        if contest.campaign_event_id:
            self.stdout.write("Este concurso possui um evento de campanha.")
            event_id = contest.campaign_event_id
            api_base = f"https://meta.wikimedia.org/w/rest.php/campaignevents/v0/event_registration/{event_id}/participants"
            params = {"include_private": "no", "uselang": "en"}
            enrollments = []
            last_participant_id = None
            has_more_results = True

            while has_more_results:
                if last_participant_id:
                    params["last_participant_id"] = last_participant_id
                response = requests.get(api_base, params=params).json()
                if not response:
                    has_more_results = False
                else:
                    enrollments.extend(self.parse_event(response))
                    last_participant_id = response[-1]['participant_id']  # Get the last participant ID for the next query
        else:
            enrollments = self.fetch_csv_data(contest)
            if enrollments:
                self.stdout.write(f"Lista de usuários coletada. ({len(enrollments)} usuários encontrados)")
            else:
                # Get saved enrollments from the database if Outreach is down
                self.stdout.write("Não foi possível coletar a lista de usuários. Usando dados salvos...")
                enrollments = Participant.objects.filter(contest=contest).values(
                    'global_id', 
                    username=F('user'), 
                    enrollment_timestamp=F('timestamp')
                )

        # Coleta ID da wiki
        wiki_id = self.fetch_wiki_id(contest)
        self.stdout.write(f"Wiki ID: {wiki_id}")

        # Processa os usuários inscritos
        self.process_enrollments(enrollments, contest, wiki_id)

        # Destrava edições bloqueadas
        self.unlock_edits(contest)
        self.stdout.write("Concluído! (2/3)")

    def get_contest(self, contest_name_id):
        """Fetches the contest instance."""
        return Contest.objects.get(name_id=contest_name_id)

    def fetch_csv_data(self, contest):
        """Fetches enrolled users from Outreach users.json endpoint."""
        self.stdout.write("Coletando lista de usuários inscritos...")
        course_slug = quote(contest.outreach_name, safe='/')
        users_url = f'https://outreachdashboard.wmflabs.org/courses/{course_slug}/users.json'
        try:
            response = requests.get(users_url, timeout=15)
            response.raise_for_status()
        except requests.exceptions.RequestException:
            return None

        users = response.json().get('course', {}).get('users', [])
        enrollments = []
        for user in users:
            if user.get('role') != 0:
                continue

            global_id = user.get('id')
            username = user.get('username')
            enrollment_timestamp = user.get('enrolled_at')
            if not all([global_id, username, enrollment_timestamp]):
                continue

            enrollments.append({
                'global_id': global_id,
                'username': username,
                'enrollment_timestamp': enrollment_timestamp,
            })

        return enrollments or None

    def parse_event(self, response):
        """Parses the event response into a list of enrollments."""
        enrollments = []
        for participant in response:
            enrollments.append({
                'global_id': participant['user_id'],
                'username': participant['user_name'],
                'enrollment_timestamp': parser.parse(participant['user_registered_at'])
            })
        return enrollments

    def parse_csv(self, csv_content):
        """Parses the CSV content into a list of enrollments."""
        csv_lines = list(csv.reader(csv_content.splitlines()))
        csv_head = csv_lines.pop(0)
        csv_num_rows = len(csv_head)

        enrollments = []
        for csv_line in csv_lines:
            if len(csv_line) != csv_num_rows:
                csv_line = self.fix_csv_line_length(csv_line, csv_num_rows)
            enrollments.append(dict(zip(csv_head, csv_line)))

        return enrollments

    def fix_csv_line_length(self, csv_line, csv_num_rows):
        """Fixes the CSV line length in case of issues."""
        if len(csv_line) < csv_num_rows:
            raise ValueError("Erro! Uma das linhas possui menos colunas que o cabeçalho.")
        extra_columns = len(csv_line) - csv_num_rows + 1
        csv_line_first_column = ",".join(csv_line[:extra_columns])
        return [csv_line_first_column] + csv_line[extra_columns:]

    def fetch_wiki_id(self, contest):
        """Fetches the wiki ID from the contest API."""
        self.stdout.write("Coletando ID da wiki...")
        params = {"action": "query", "format": "json", "meta": "siteinfo"}
        response = requests.get(
            contest.api_endpoint,
            params=params,
            headers=WIKIMEDIA_API_HEADERS,
            timeout=15,
        ).json()
        return response['query']['general']['wikiid']

    def process_enrollments(self, enrollments, contest, wiki_id):
        """Processes each enrollment, updating or inserting users."""
        # Filter out enrollments with empty or invalid global_id
        valid_global_ids = [
            enrollment['global_id']
            for enrollment in enrollments
            if enrollment.get('global_id') not in [None, '', 0]
        ]
        # Get all participant enrollments for the specific contest
        already_enrolled_ids = Participant.objects.filter(
            contest=contest, last_enrollment__enrolled=True
        ).exclude(global_id__in=valid_global_ids).values_list('global_id', flat=True)

        for global_id in already_enrolled_ids:
            self.stdout.write(f"Usuário {global_id} não está mais inscrito. Desinscrevendo...")
            unenroll = ParticipantEnrollment.objects.create(
                contest=contest,
                enrolled=False,
                user=Participant.objects.get(global_id=global_id, contest=contest)
            )
            Participant.objects.filter(global_id=global_id, contest=contest).update(last_enrollment=unenroll)

        for enrollment in enrollments:
            global_id = enrollment['global_id']
            username = enrollment['username']
            timestamp = enrollment['enrollment_timestamp']
            if not isinstance(timestamp, datetime):
                timestamp = parser.parse(timestamp)
            timestamp = timezone.make_aware(timestamp, dt_timezone.utc) if timezone.is_naive(timestamp) else timestamp.astimezone(dt_timezone.utc)
            self.stdout.write(f"Coletando informações do usuário {username} ({global_id})...")

            self.insert_or_update_user(global_id, username, contest, wiki_id, timestamp)

    def insert_or_update_user(self, global_id, username, contest, wiki_id, timestamp):
        """Inserts or updates the user in the Participant table."""
        if global_id:         
            try:
                participant = Participant.objects.get(global_id=global_id, contest=contest)
                local_id = participant.local_id
                self.stdout.write(f"Usuário {username} já está na tabela. Ignorando...")
            except Participant.DoesNotExist:
                participant = None
                local_id = self.add_user_contest(global_id, contest, wiki_id, timestamp, username)
                self.stdout.write(f"Usuário {username} inserido com sucesso!")
        else:
            self.stdout.write(f"Usuário {username} sem ID global.")
            local_id = None
            try:
                participant = Participant.objects.get(user=username, contest=contest)
            except Participant.DoesNotExist:
                self.stdout.write(f"Usuário {username} não encontrado. Inserindo...")
                self.add_user_contest(global_id, contest, wiki_id, timestamp, username)
                participant = None

        
        if participant and participant.user != username:
            self.stdout.write(f"Usuário {username} mudou de nome. Atualizando...")
            Participant.objects.filter(global_id=global_id, contest=contest).update(user=username)

        if not local_id:
            self.stdout.write(f"Usuário {username} não encontrado. Ignorando...")
            return None
        else:
            self.check_participant_enrollment(local_id, contest, timestamp)
            self.update_user_edits(local_id, contest, timestamp)

    def add_user_contest(self, global_id, contest, wiki_id, timestamp, username):
        """Adds a user to the contest."""
        if global_id:
            centralauth_response = self.fetch_user_data(global_id, contest)
            centralauth_merged = centralauth_response['query']['globaluserinfo']['merged']
            local_id = next((merged['id'] for merged in centralauth_merged if merged['wiki'] == wiki_id), None)
            user = centralauth_response['query']['globaluserinfo']['name']
            attached = centralauth_response['query']['globaluserinfo']['registration']
        else:
            local_id = None
            user = None
            attached = None
            global_id = None
            user=username

        new_participant, created = Participant.objects.get_or_create(
            contest=contest,
            user=user,
            defaults={
                'timestamp': timestamp,
                'global_id': global_id,
                'local_id': local_id,
                'attached': attached
            }
        )
        
        if not created:
            new_participant.timestamp = timestamp
            new_participant.global_id = global_id
            new_participant.local_id = local_id
            new_participant.attached = attached
            new_participant.save()

        if global_id and local_id:
            new_enrollment = ParticipantEnrollment.objects.create(
                contest=contest,
                user=new_participant
            )
            Participant.objects.filter(global_id=global_id, contest=contest).update(last_enrollment=new_enrollment)

        return local_id

    def fetch_user_data(self, global_id, contest):
        """Fetches user data from the contest API."""
        params = {
            "action": "query",
            "format": "json",
            "meta": "globaluserinfo",
            "guiprop": "merged",
            "formatversion": "2",
            "guiid": global_id
        }
        return requests.get(
            contest.api_endpoint,
            params=params,
            headers=WIKIMEDIA_API_HEADERS,
            timeout=15,
        ).json()

    def check_participant_enrollment(self, local_id, contest, timestamp):
        """Check if the participant is enrolled in the contest and creates an enrollment if necessary."""
        try:
            participant = Participant.objects.get(local_id=local_id, contest=contest)
        except Participant.DoesNotExist:
            self.stdout.write(f"Usuário com ID local {local_id} não encontrado. Ignorando...")
            return None

        last_enrollment = participant.last_enrollment
        if last_enrollment and last_enrollment.enrolled:
            self.stdout.write(f"Usuário com ID local {local_id} já está inscrito. Ignorando...")
            return None

        if last_enrollment and not last_enrollment.enrolled:
            self.stdout.write(f"Usuário com ID local {local_id} não está mais inscrito. Reinscrevendo...")
            new_enrollment = ParticipantEnrollment.objects.create(
                contest=contest,
                user=participant,
                enrolled=True
            )
            Participant.objects.filter(local_id=local_id, contest=contest).update(last_enrollment=new_enrollment)

    def update_user_edits(self, local_id, contest, timestamp):
        """Updates user edits in the Edit table."""
        self.stdout.write(f"Atualizando edições do usuário com ID local {local_id}...")
        participant = Participant.objects.get(local_id=local_id, contest=contest, last_enrollment__enrolled=True)
        
        timestamp = timezone.make_aware(timestamp, dt_timezone.utc) if timezone.is_naive(timestamp) else timestamp.astimezone(dt_timezone.utc)

        Edit.objects.filter(user_id=local_id, contest=contest, participant=None).update(participant=participant)

        edits = Edit.objects.filter(user_id=local_id, timestamp__gte=timestamp, contest=contest, last_qualification=None)
        edits_to_update = []
        for edit in edits:
            qualification = Qualification.objects.create(contest=contest, diff=edit)
            edit.last_qualification = qualification
            edits_to_update.append(edit)
        Edit.objects.bulk_update(edits_to_update, ['last_qualification'])

    def unlock_edits(self, contest):
        """Unlocks any remaining locked edits in the Edit table."""
        self.stdout.write("Destravando edições...")

        lockeds = Edit.objects.filter(
            contest=contest,
            last_evaluation__status__in=['2', '3'],
        )

        for locked in lockeds:
            unlocked = Evaluation.objects.create(
                contest=contest,
                diff=locked,
            )
            locked.last_evaluation = unlocked
            locked.save(update_fields=['last_evaluation'])
            
        self.stdout.write("Edições destravadas com sucesso!")