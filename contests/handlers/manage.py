from contests.models import Contest, Evaluator, Edit, Participant, Article
from credentials.models import Profile

class ManageHandler():
    def execute(self, request):
        group = request.user.profile.group_set.first()
        message = None

        if request.method == 'POST':
            name_id = request.POST.get('name_id')
            if request.POST.get('do_create') is not None:
                if Contest.objects.filter(name_id=name_id).exists():
                    raise PermissionDenied("Contest already exists.")
                else:
                    source = request.POST.get('source')
                    control_method = request.POST.get('control_method')
                    contest = Contest.objects.create(
                        name_id=name_id,
                        start_time=request.POST.get('start_time'),
                        end_time=request.POST.get('end_time'),
                        name=request.POST.get('name'),
                        group=group,
                        revert_time=request.POST.get('revert_time'),
                        official_list_pageid=request.POST.get('official_list_pageid'),
                        category_pageid=request.POST.get('sourceid') if source == 'category' else None,
                        category_petscan=request.POST.get('sourceid') if source == 'petscan' else None,
                        endpoint=request.POST.get('endpoint'),
                        api_endpoint=request.POST.get('api_endpoint'),
                        outreach_name=request.POST.get('outreach_name') if control_method == 'outreach' else None,
                        campaign_event_id=request.POST.get('campaign_event_id') if control_method == 'campaign' else None,
                        bytes_per_points=request.POST.get('bytes_per_points'),
                        max_bytes_per_article=request.POST.get('max_bytes_per_article'),
                        minimum_bytes=request.POST.get('minimum_bytes') or None,
                        pictures_per_points=request.POST.get('pictures_per_points') or 5,
                        pictures_mode=request.POST.get('pictures_mode') or 0,
                        max_pic_per_article=request.POST.get('max_pic_per_article') or None,
                        theme=request.POST.get('theme') or 'red',
                        color=request.POST.get('color') or '',
                    )
                    Evaluator.objects.create(
                        contest=contest, 
                        profile=self.get_or_create_profile(request.POST.get('manager')), 
                        user_status='G'
                    )
                    message = 'do_create'

            elif request.POST.get('do_edit') is not None:
                if Contest.objects.filter(name_id=name_id).exists():
                    contest = Contest.objects.get(name_id=name_id)
                    source = request.POST.get('source')
                    control_method = request.POST.get('control_method')
                    contest.start_time = request.POST.get('start_time')
                    contest.end_time = request.POST.get('end_time')
                    contest.name = request.POST.get('name')
                    contest.revert_time = request.POST.get('revert_time')
                    contest.official_list_pageid = request.POST.get('official_list_pageid')
                    contest.category_pageid = request.POST.get('sourceid') if source == 'category' else None
                    contest.category_petscan = request.POST.get('sourceid') if source == 'petscan' else None
                    contest.endpoint = request.POST.get('endpoint')
                    contest.api_endpoint = request.POST.get('api_endpoint')
                    contest.outreach_name = request.POST.get('outreach_name') if control_method == 'outreach' else None
                    contest.campaign_event_id = request.POST.get('campaign_event_id') if control_method == 'campaign' else None
                    contest.bytes_per_points = request.POST.get('bytes_per_points')
                    contest.max_bytes_per_article = request.POST.get('max_bytes_per_article')
                    contest.minimum_bytes = request.POST.get('minimum_bytes') or None
                    contest.pictures_per_points = request.POST.get('pictures_per_points') or 5
                    contest.pictures_mode = request.POST.get('pictures_mode') or 0
                    contest.max_pic_per_article = request.POST.get('max_pic_per_article') or None
                    contest.theme = request.POST.get('theme') or 'red'
                    contest.color = request.POST.get('color') or ''
                    contest.save()
                    message = 'do_edit'

            elif request.POST.get('do_manager') is not None:
                if Contest.objects.filter(name_id=name_id).exists():
                    contest = Contest.objects.get(name_id=name_id)
                    Evaluator.objects.filter(
                        contest=contest,
                    ).update(user_status='P')
                    evaluator, _ = Evaluator.objects.get_or_create(
                        contest=contest, 
                        profile=self.get_or_create_profile(request.POST.get('manager'))
                    )
                    evaluator.user_status = 'G'
                    evaluator.save()
                    message = 'do_manager'

            elif request.POST.get('do_restart') is not None:
                if Contest.objects.filter(name_id=name_id).exists():
                    contest = Contest.objects.get(name_id=name_id)
                    Edit.objects.filter(contest=contest).delete()
                    Participant.objects.filter(contest=contest).delete()
                    Article.objects.filter(contest=contest).delete()
                    message = 'do_restart'

            elif request.POST.get('do_delete') is not None:
                if Contest.objects.filter(name_id=name_id).exists():
                    Contest.objects.get(name_id=name_id).delete()
                    message = 'do_delete'

        contests = list(Contest.objects.filter(group=group).order_by('-start_time'))
        contests.append(Contest())
        return {
            'contests': contests,
            'group': group,
            'message': message
        }

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
        response = requests.get(self.contest.api_endpoint, params=api_params)
        data = response.json()

        if 'query' in data and 'globaluserinfo' in data['query'] and 'id' in data['query']['globaluserinfo']:
            global_id = data['query']['globaluserinfo']['id']
            return Profile.objects.create(global_id=global_id, username=username)
