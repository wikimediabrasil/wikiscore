import requests
from datetime import timedelta, datetime, timezone
from django.db.models import Count, Sum, Subquery, OuterRef, Case, When, Q
from django.db.models.functions import TruncDay
from contests.models import Evaluator, Edit, Participant, Qualification, Article
from contests.utils import WIKIMEDIA_API_HEADERS

class ContestHandler():
    def __init__(self, contest):
        self.contest = contest

    def execute(self, request):
        contest = self.contest
        is_evaluator = self.check_evaluator(request.user)

        date_range = self.get_date_range(contest.start_time, contest.end_time)
        
        approved_edits = self.get_approved_edits(contest)
        
        stats = {
            'new_articles': self.get_stat_by_date(Edit, contest, 'new_page', True),
            'new_participants': self.get_stat_by_date(Participant, contest),
            'total_edits': self.get_stat_by_date(Edit, contest),
            'total_bytes': self.get_stat_by_date(Edit, contest, 'orig_bytes__gte', 0, 'orig_bytes', sum_field=True),
            'valid_edits': self.get_stat_by_date(Edit, contest, 'pk__in', approved_edits),
            'valid_bytes': self.get_stat_by_date(Edit, contest, 'pk__in', approved_edits, 'orig_bytes', sum_field=True)
        }

        return self.build_response_dict(stats, date_range, contest, is_evaluator)

    def check_evaluator(self, user):
        if user.is_anonymous:
            return False
        try:
            Evaluator.objects.get(contest=self.contest, profile=user.profile)
            return True
        except Evaluator.DoesNotExist:
            return False

    def get_date_range(self, start_date, end_date):
        return [start_date + timedelta(days=x) for x in range((end_date - start_date).days + 1)]

    def get_approved_edits(self, contest):
        return Edit.objects.filter(
            contest=contest,
            last_evaluation__valid_edit=True
        )

    def get_stat_by_date(self, model, contest, filter_field=None, filter_value=None, value_field='id', sum_field=False):
        queryset = model.objects.filter(contest=contest, timestamp__range=(contest.start_time, contest.end_time))
        
        if filter_field and filter_value is not None:
            queryset = queryset.filter(**{filter_field: filter_value})

        annotated_queryset = queryset.annotate(date=TruncDay('timestamp')).values('date')
        
        if sum_field:
            return {entry['date']: entry['sum_value'] for entry in annotated_queryset.annotate(sum_value=Sum(value_field)).order_by('date')}
        
        return {entry['date']: entry['count'] for entry in annotated_queryset.annotate(count=Count(value_field)).order_by('date')}

    def most_edited_article(self, contest):
        most_edited = (
            Edit.objects.filter(contest=contest)
            .values('article', 'article__title')
            .annotate(total=Count('diff'))
            .order_by('-total')
            .first()
        )
        return most_edited

    def biggest_delta(self, contest):
        biggest_delta = (
            Edit.objects.filter(contest=contest)
            .values('article', 'article__title')
            .annotate(total=Sum(Case(
                When(last_evaluation__valid_edit=True, then='last_evaluation__real_bytes'),
                default='orig_bytes')))
            .order_by('-total')
            .first()
        )
        return biggest_delta

    def biggest_edit(self, contest):
        biggest_edit = (
            Edit.objects.filter(contest=contest, last_evaluation__valid_edit=True)
            .values('article', 'article__title', 'diff', 'last_evaluation__real_bytes')
            .order_by('-last_evaluation__real_bytes')
            .first()
        )
        return biggest_edit

    def count_participants(self, contest):
        return Participant.objects.filter(
            contest=contest, timestamp__isnull=False
        ).filter(
            Q(last_enrollment__enrolled=True) | Q(last_enrollment__isnull=True)
        ).count()

    def count_articles(self, contest):
        list_ = []
        api_params = {
            'action': 'query',
            'generator': 'links',
            'pageids': contest.official_list_pageid,
            'gplnamespace': 0,
            'gpllimit': 'max',
            'format': 'json'
        }
        response = requests.get(contest.api_endpoint, params=api_params, headers=WIKIMEDIA_API_HEADERS).json()
        if 'query' not in response:
            return list_

        list_.extend(response['query']['pages'])
        while 'continue' in response:
            api_params['gplcontinue'] = response['continue']['gplcontinue']
            response = requests.get(contest.api_endpoint, params=api_params, headers=WIKIMEDIA_API_HEADERS).json()
            list_.extend(response['query']['pages'])

        return len(list_)

    def edits_summary(self, contest):
        timecut = datetime(2024, 10, 1, tzinfo=timezone.utc)
        edits_summary = (
            Edit.objects.filter(contest=contest)
            .aggregate(
                new_pages=Sum(Case(When(new_page=True, then=1), default=0)),
                edited_articles=Count('article', filter=Q(participant__isnull=False) & Q(contest__start_time__gt=timecut) | Q(contest__start_time__lte=timecut), distinct=True),
                valid_edits=Sum(Case(When(last_evaluation__valid_edit=True, then=1), default=0)),
                all_bytes=Sum(Case(
                    When(last_evaluation__valid_edit=True, then='last_evaluation__real_bytes'),
                    When(orig_bytes__gt=0, then='orig_bytes'),
                    default=0
                )),
            )
        )
        return edits_summary
    
    def build_response_dict(self, stats, date_range, contest, is_evaluator):
        response_data = {
            'contest': contest,
            'date': [],
            'new_articles': [],
            'new_participants': [],
            'total_edits': [],
            'total_bytes': [],
            'valid_edits': [],
            'valid_bytes': [],
            'is_evaluator': is_evaluator,
            'most_edited': self.most_edited_article(contest),
            'biggest_delta': self.biggest_delta(contest),
            'biggest_edit': self.biggest_edit(contest),
            'edits_summary': self.edits_summary(contest),
            'participants': self.count_participants(contest),
            'articles': self.count_articles(contest),
        }

        for date in date_range:
            day_diff = str(abs(date - contest.start_time).days)
            response_data['date'].append(day_diff)
            response_data['new_articles'].append(str(stats['new_articles'].get(date, 0)))
            response_data['new_participants'].append(str(stats['new_participants'].get(date, 0)))
            response_data['total_edits'].append(str(stats['total_edits'].get(date, 0)))
            response_data['total_bytes'].append(str(stats['total_bytes'].get(date, 0)))
            response_data['valid_edits'].append(str(stats['valid_edits'].get(date, 0)))
            response_data['valid_bytes'].append(str(stats['valid_bytes'].get(date, 0)))

        for key in response_data:
            if isinstance(response_data[key], list):
                response_data[key] = ', '.join(response_data[key])

        return response_data
