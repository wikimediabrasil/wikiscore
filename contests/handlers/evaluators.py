import requests
from credentials.models import Profile
from django.db.models import Count, Q
from contests.models import Evaluator, Edit
from contests.utils import WIKIMEDIA_API_HEADERS

class EvaluatorsHandler:
    def __init__(self, contest):
        self.contest = contest

    def execute(self, request):
        evaluator = self.get_current_evaluator(request)
        
        if request.method == 'POST' and evaluator.user_status == 'G':
            if request.POST.get('new'):
                self.add_new_evaluator(request.POST.get('new'))

            if request.POST.get('user'):
                self.update_evaluator_status(request)

        return {
            'contest': self.contest,
            'evaluators': self.get_evaluators_by_status('A'),
            'managers': self.get_evaluators_by_status('G'),
            'disabled': self.get_disabled_evaluators(),
            'status': evaluator.user_status,
        }

    def get_current_evaluator(self, request):
        return Evaluator.objects.get(contest=self.contest, profile=request.user.profile)

    def add_new_evaluator(self, username):
        profile = self.get_or_create_profile(username)
        if profile:
            Evaluator.objects.get_or_create(
                contest=self.contest,
                profile=profile,
                defaults={'user_status': 'A'},
            )

    def get_or_create_profile(self, username):
        try:
            return Profile.objects.get(username=username)
        except Profile.DoesNotExist:
            return self.fetch_profile_from_api(username)

    def fetch_profile_from_api(self, username):
        api_params = {
            'action': 'query',
            'meta': 'globaluserinfo',
            'guiuser': username,
            'format': 'json',
        }
        response = requests.get(self.contest.api_endpoint, params=api_params, headers=WIKIMEDIA_API_HEADERS)
        data = response.json()

        if 'query' in data and 'globaluserinfo' in data['query'] and 'id' in data['query']['globaluserinfo']:
            global_id = data['query']['globaluserinfo']['id']
            return Profile.objects.create(global_id=global_id, username=username)

    def update_evaluator_status(self, request):
        username = request.POST.get('user')
        if request.POST.get('off'):
            self.update_status(username, 'P')
        elif request.POST.get('on'):
            self.update_status(username, 'A')
        elif request.POST.get('reset'):
            self.reset_evaluations(username)

    def update_status(self, username, status):
        Evaluator.objects.filter(
            contest=self.contest,
            profile__username=username,
        ).update(user_status=status)

    def reset_evaluations(self, username):
        Edit.objects.filter(
            contest=self.contest,
            last_evaluation__evaluator__profile__username=username,
        ).update(last_evaluation=None)

    def get_evaluators_by_status(self, status):
        return Profile.objects.filter(
            evaluator__contest=self.contest,
            evaluator__user_status=status,
        ).annotate(
            evaluation_count=Count('evaluator__evaluation'),
            filter=Q(evaluator__evaluation__status='1')
        ).values('global_id', 'username', 'evaluation_count')

    def get_disabled_evaluators(self):
        return Profile.objects.filter(
            Q(evaluator__contest=self.contest, evaluator__user_status='P') |
            ~Q(evaluator__contest=self.contest)
        ).annotate(
            evaluation_count=Count('evaluator__evaluation'),
            filter=Q(evaluator__evaluation__status='1')
        ).values('global_id', 'username', 'evaluation_count')