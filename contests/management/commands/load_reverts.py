import requests
import time
from datetime import datetime
from django.core.management.base import BaseCommand
from django.db import connection
from contests.models import Contest, Article, Edit, Qualification
from django.db.models import OuterRef, Subquery
from contests.utils import WIKIMEDIA_API_HEADERS

class Command(BaseCommand):
    help = 'Update reverts'

    def add_arguments(self, parser):
        parser.add_argument('contest', type=str, help="Nome ID do concurso")

    def handle(self, *args, **options):
        contest_name_id = options.get('contest')
        contest = Contest.objects.get(name_id=contest_name_id)

        # Coleta lista de edições ativas no concurso
        diffs = Edit.objects.filter(contest=contest, last_qualification__status=1).values_list('diff', flat=True)

        # Loop para análise de cada edição
        for diff in diffs:

            # Coleta tags da revisão
            revisions_api_params = {
                "action": "query",
                "format": "json",
                "prop": "revisions",
                "rvprop": "sha1|tags",
                "revids": diff,
            }
            revisions_api = requests.get(contest.api_endpoint, params=revisions_api_params, headers=WIKIMEDIA_API_HEADERS).json()
            revisions_api_query = revisions_api.get('query', {})
            revision = None

            if 'pages' in revisions_api_query:
                self.stdout.write(f"Revisão: {diff}")
                revision_page = next(iter(revisions_api_query['pages'].values()), None)
                revision = revision_page['revisions'][0] if revision_page and 'revisions' in revision_page else None

            # Marca edição caso tenha sido revertida ou eliminada
            if (
                'badrevids' in revisions_api_query
                or (revision and 'sha1hidden' in revision)
                or (revision and 'mw-reverted' in revision['tags'])
            ):
                new_qualification = Qualification.objects.create(
                    contest=contest,
                    diff=Edit.objects.get(contest=contest, diff=diff),
                    status=0,
                )
                Edit.objects.filter(contest=contest, diff=diff).update(last_qualification=new_qualification)
                self.stdout.write(f"Marcada edição {diff} como revertida.")

        # Encerra script
        self.stdout.write("Concluído! (3/3)")
