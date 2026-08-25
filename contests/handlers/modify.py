import requests
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from contests.models import Evaluator, Edit, Evaluation, Qualification
from contests.models import Contest
from contests.utils import WIKIMEDIA_API_HEADERS


class ModifyHandler():
    def __init__(self, contest):
        self.contest = contest

    def execute(self, request):
        if request.method == 'POST' and request.POST.get('diff'):
            diff = request.POST.get('diff')
            edit = self.get_edit(diff)

            if not edit:
                return {'contest': self.contest, 'diff': diff, 'content': None}

            allowed = self.is_allowed(request, edit)
            content, author, comment = self.get_comparison_data(diff)
            history_qualifications = self.get_history_qualifications(edit)
            history_evaluations = self.get_history_evaluations(edit)

            evaluation = None
            if request.POST.get('obs'):
                evaluation = self.create_evaluation(request, edit, allowed)

            return {
                'contest': self.contest, 
                'edit': edit, 
                'diff': diff,
                'evaluation': evaluation,
                'allowed': allowed,
                'content': content,
                'author': author,
                'comment': comment,
                'history_qualifications': history_qualifications,
                'history_evaluations': history_evaluations,
            }
        else:
            return {'contest': self.contest, 'edit': None}

    def get_edit(self, diff):
        try:
            return Edit.objects.get(contest=self.contest, diff=diff)
        except Edit.DoesNotExist:
            return False

    def is_allowed(self, request, edit):
        evaluator = Evaluator.objects.get(contest=self.contest, profile=request.user.profile)
        return evaluator.user_status == 'G' or edit.last_evaluation.evaluator.profile == request.user.profile

    def get_comparison_data(self, diff):
        compare_params = {
            'action': 'compare',
            'prop': 'title|diff|comment|user|ids',
            'format': 'json',
            'fromrev': diff,
            'torelative': 'prev',
        }
        compare = requests.get(self.contest.api_endpoint, params=compare_params, headers=WIKIMEDIA_API_HEADERS).json().get('compare', {})
        return compare.get('*', ''), compare.get('touser', ''), compare.get('tocomment', '')

    def get_history_qualifications(self, edit):
        return Qualification.objects.filter(
            contest=self.contest, 
            diff=edit
        ).select_related('evaluator__profile').order_by('-when')

    def get_history_evaluations(self, edit):
        return Evaluation.objects.filter(
            contest=self.contest, 
            diff=edit
        ).select_related('evaluator__profile').order_by('-when')

    def create_evaluation(self, request, edit, allowed):
        if allowed:
            evaluation = Evaluation.objects.create(
                contest=self.contest,
                evaluator=Evaluator.objects.get(contest=self.contest, profile=request.user.profile),
                diff=edit,
                valid_edit=True if request.POST.get('valid') == '1' else False,
                pictures=request.POST.get('pic') if request.POST.get('pic').isnumeric() else 0,
                real_bytes=request.POST.get('overwrite') or edit.orig_bytes,
                status=1,
                obs=request.POST.get('obs'),
            )
            edit.last_evaluation = evaluation
            edit.save()
            return True
        else:
            raise PermissionDenied("You are not allowed to perform this action.")
        