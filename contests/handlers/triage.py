import requests
from datetime import datetime, timedelta
from django.shortcuts import render, redirect, get_object_or_404
from contests.models import Contest, Edit, Evaluation, Participant, ParticipantEnrollment, Qualification, Evaluator
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum, Case, When, Value, IntegerField, Q, OuterRef, Subquery, Count


class TriageHandler:
    def __init__(self, contest, user, api_endpoint):
        self.contest = contest
        self.user = user
        self.api_endpoint = api_endpoint

    def do_evaluate(self, request):
        if request.POST.get('skip'):
            diff = request.POST.get('diff') or None
            if not diff:
                raise ValueError('Edit not found')
            else:
                if self.skip_edit(diff):
                    return {'action': 'skip'}

        elif request.POST.get('release'):
            if self.release_edit():
                return {'action': 'release'}

        elif request.POST.get('unhold'):
            if Evaluator.objects.get(contest=self.contest, profile=self.user.profile).user_status != 'G':
                raise PermissionError('User is not a group member')
            else:
                if self.unhold_edit():
                    return {'action': 'unhold'}

        else:
            return self.evaluate_edit(request)


    def get_evaluate(self, request):
        # Fetch the contest data
        contest = self.contest  
        return_dict = {'contest': contest }
          
        # Check if the update start time is greater than the end time (indicating an update is in progress)
        if (
            contest.started_update is not None and contest.finished_update is None
        ) or (
            contest.started_update is not None and contest.finished_update is not None and contest.started_update > contest.finished_update
        ):
            return_dict.update({'error': 'updating'})
        
        # Fetch the next available edit for triage
        next_edit = self.get_next_edit(contest)
        if not next_edit:
            return_dict.update({'error': 'noedit'})
        else:
            # Mark the edit as being held by the current user
            hold = self.hold_edit(next_edit, request.user)
            if not hold:
                return_dict.update({'error': 'held'})
            
            # Fetch comparison data for the edit
            compare_data, compare_data_mobile = self.fetch_compare_data(contest.api_endpoint, next_edit.diff)
            if not compare_data:
                self.mark_edit_reverted(next_edit)
                return_dict.update({'error': 'reverted'})
            else:
                # Fetch the revision history of the article related to the edit
                revision_history = self.fetch_revision_history(contest.api_endpoint, next_edit.article.articleID, contest.start_time)
                last_revision = revision_history[-1] if revision_history else None

                # Validate the parent ID of the last (oldest) revision
                if last_revision and not self.is_valid_parentid(last_revision['parentid']):
                    raise ValueError('Parent ID is not a number')

                # Update the revision history with data from the previous revision
                self.update_history_with_previous_revision(contest.api_endpoint, revision_history, last_revision)

                # Build the context for rendering the template
                render_context = self.build_context(revision_history, next_edit.diff)

                return_dict.update({
                    'context': render_context,
                    'edit': next_edit,
                    'compare': compare_data,
                    'compare_html': compare_data['*'],
                    'compare_mobile': compare_data_mobile,
                    'compare_mobile_html': compare_data_mobile['*'],
                    'history': revision_history,
                })

        # Calculate edit statistics (e.g., on queue, on hold)
        edit_stats = self.calculate_edit_stats(contest)
        return_dict.update({
            'onqueue': edit_stats['onqueue'],
            'onwait': edit_stats['onwait'],
            'onskip': edit_stats['onskip'],
            'onhold': edit_stats['onhold'],
            'onpending': edit_stats['onhold'] + edit_stats['onskip'],
        })
        
        # Return the data for rendering the template
        return return_dict 

    def skip_edit(self, diff):
        evaluation = Evaluation.objects.create(
            contest=self.contest,
            evaluator=Evaluator.objects.get(contest=self.contest, profile=self.user.profile),
            diff=Edit.objects.get(contest=self.contest, diff=diff),
            status='3'
        )
        Edit.objects.filter(contest=self.contest, diff=diff).update(last_evaluation=evaluation)
        return evaluation

    def release_edit(self):
        evaluator = Evaluator.objects.get(contest=self.contest, profile=self.user.profile)

        skipped = Edit.objects.filter(
            contest=self.contest, 
            last_evaluation__evaluator=evaluator, 
            last_evaluation__status='3'
        )

        for skip in skipped:
            evaluation = Evaluation.objects.create(
                contest=self.contest,
                evaluator=evaluator,
                diff=skip,
                status='0' # Status '0' indicates the edit is pending
            )
            Edit.objects.filter(contest=self.contest, diff=skip.diff).update(last_evaluation=evaluation)

        return skipped

    def evaluate_edit(self, request):

        diff = request.POST.get('diff') or None
        if not diff:
            raise ValueError('Edit not found')

        picture_input = request.POST.get('picture', 'nao')
        if self.contest.pictures_mode == 2 and picture_input and picture_input.isnumeric():
            picture = picture_input
        else:
            picture = True if picture_input == 'sim' else False

        overwrite_value = request.POST.get('overwrite')
        real_bytes = int(overwrite_value) if overwrite_value and overwrite_value.isnumeric() else Edit.objects.get(contest=self.contest, diff=diff).orig_bytes

        evaluation = Evaluation.objects.create(
            contest=self.contest,
            evaluator=Evaluator.objects.get(contest=self.contest, profile=self.user.profile),
            diff=Edit.objects.get(contest=self.contest, diff=diff),
            valid_edit=True if request.POST.get('valid') == 'sim' else False,
            pictures=picture,
            real_bytes=real_bytes,
            status='1',
            obs=request.POST.get('obs') or None
        )
        Edit.objects.filter(contest=self.contest, diff=diff).update(last_evaluation=evaluation)

        return evaluation.__dict__

    def get_next_edit(self, contest):

        edit = Edit.objects.filter(
            contest=contest,
            orig_bytes__gte=contest.minimum_bytes or 1,
            timestamp__lte=timezone.now() - timedelta(hours=contest.revert_time),
            participant__isnull=False,
            last_qualification__status=1
        ).filter(
            Q(last_evaluation=None) |
            Q(last_evaluation__status='0') |
            (Q(last_evaluation__status='2') & Q(last_evaluation__evaluator=Evaluator.objects.get(contest=contest, profile=self.user.profile)))
        ).order_by('timestamp').first()

        return edit

    def unhold_edit(self):

        lockeds = Edit.objects.filter(
            contest=self.contest,
            last_evaluation__status__in=['2', '3'],
        )

        for locked in lockeds:
            evaluation = Evaluation.objects.create(
                contest=self.contest,
                diff=locked.diff,
                status='0' # Status '0' indicates the edit is pending
            )
            Edit.objects.filter(contest=self.contest, diff=locked.diff).update(last_evaluation=evaluation)

        return lockeds

    # Function to mark the edit as being held by the user
    def hold_edit(self, edit, user):

        # Start an atomic transaction
        with transaction.atomic():
            # Lock the edit row to avoid race conditions
            held_edit = Edit.objects.select_for_update().filter(
                diff=edit.diff,
                contest=self.contest
            ).filter(
                Q(last_evaluation=None) |
                Q(last_evaluation__status='0') |
                (Q(last_evaluation__status='2') & Q(last_evaluation__evaluator=Evaluator.objects.get(contest=self.contest, profile=self.user.profile)))
            ).first()

            if held_edit:
                # Check if the edit is already held by the same user (status='2' and evaluator is the current user)
                if held_edit.last_evaluation and held_edit.last_evaluation.status == '2' and held_edit.last_evaluation.evaluator.profile == self.user.profile:
                    # Edit is already held by the current user, no need to create a new evaluation
                    return True
                
                # Create a new evaluation if the edit is not already held by the current user
                evaluator = Evaluator.objects.get(contest=self.contest, profile=self.user.profile)
                evaluation = Evaluation.objects.create(
                    contest=self.contest,
                    evaluator=evaluator,
                    diff=held_edit,
                    status='2'  # Status '2' indicates the edit is on hold
                )

                # Update the edit's last_evaluation field
                held_edit.last_evaluation = evaluation
                held_edit.save(update_fields=['last_evaluation'])

                # Return success after creating and updating
                return True
            else:
                # Handle the case where the edit is already held by another user
                return False

    # Function to fetch comparison data for the edit
    def fetch_compare_data(self, api_endpoint, diff):
        compare_params = {
            'action': 'compare',
            'prop': 'title|diff|comment|user|ids',
            'format': 'json',
            'fromrev': diff,
            'torelative': 'prev',
        }
        compare = requests.get(api_endpoint, params=compare_params).json().get('compare', {})
        
        compare_params['difftype'] = 'inline'
        compare_mobile = requests.get(api_endpoint, params=compare_params).json().get('compare', {})
        
        return compare, compare_mobile

    # Function to mark the edit as reverted
    def mark_edit_reverted(self, edit):
        edit.reverted = True
        edit.save()

    # Function to fetch the revision history of the article related to the edit
    def fetch_revision_history(self, api_endpoint, article_id, start_time):
        history_params = {
            'action': 'query',
            'format': 'json',
            'prop': 'revisions',
            'pageids': article_id,
            'rvprop': 'timestamp|user|size|ids',
            'rvlimit': 'max',
            'rvend': start_time.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
        }
        return requests.get(api_endpoint, params=history_params).json().get('query', {}).get('pages', {}).get(str(article_id), {}).get('revisions', [])

    # Function to validate the parent ID of the last revision
    def is_valid_parentid(self, parentid):
        return isinstance(parentid, int) and parentid >= 0

    # Function to update the revision history with data from the previous revision
    def update_history_with_previous_revision(self, api_endpoint, revision_history, last_revision):
        if last_revision and last_revision['parentid'] != 0:
            previous_revision_params = {
                'action': 'compare',
                'format': 'json',
                'fromrev': last_revision['revid'],
                'torelative': 'prev',
                'prop': 'size',
            }
            previous_revision = requests.get(api_endpoint, params=previous_revision_params).json().get('compare', {})
            revision_history.append({
                'size': previous_revision.get('fromsize', 0),
                'timestamp': '1970-01-01T00:00:00',
                'user': 'None',
                'revid': 0,
            })

    # Function to build the context for rendering the template
    def build_context(self, revision_history, current_diff):
        context = []
        for i, edit in enumerate(revision_history):
            if i + 1 < len(revision_history):
                delta = edit['size'] - revision_history[i + 1]['size']
            else:
                delta = edit['size']

            if delta > 0:
                delta_color = 'green'
            elif delta < 0:
                delta_color = 'red'
            else:
                delta_color = 'grey'
                
            history_class = 'w3-small w3-leftbar w3-border-grey w3-padding-small' if edit['revid'] == current_diff else 'w3-small'
            
            if edit['revid'] != 0:
                context.append({
                    'class': history_class,
                    'user': edit['user'],
                    'timestamp': edit['timestamp'],
                    'color': delta_color,
                    'bytes': delta,
                    'revid': edit['revid'],
                })
        return context

    # Function to calculate edit statistics (e.g., on queue, on hold)
    def calculate_edit_stats(self, contest):

        # Annotations for different statuses
        stats = Edit.objects.filter(contest=contest).aggregate(
            onqueue=Count('pk', filter=Q(
                last_qualification__status='1',
                orig_bytes__gte=contest.minimum_bytes or 1,
                timestamp__lte=timezone.now() - timedelta(hours=contest.revert_time),
                participant__isnull=False
            ) & ~Q(last_evaluation__status__in=['1', '2', '3'])),
            onwait=Count('pk', filter=Q(
                last_qualification__status='1',
                orig_bytes__gte=contest.minimum_bytes or 1,
                timestamp__gte=timezone.now() - timedelta(hours=contest.revert_time),
                participant__isnull=False
            ) & ~Q(last_evaluation__status__in=['1', '2', '3'])),
            onhold=Count('pk', filter=Q(last_evaluation__status='2')),
            onskip=Count('pk', filter=Q(last_evaluation__status='3'))
        )

        return stats
