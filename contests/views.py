import zlib
from django.http import HttpResponse
from django.conf import settings
from django.utils import translation
from django.template import loader
from django.core.exceptions import PermissionDenied, BadRequest
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_GET, require_http_methods
from functools import wraps
from collections import defaultdict
from pathlib import Path
from .models import Contest, Edit, Qualification, Evaluator
from .handlers.triage import TriageHandler
from .handlers.contest import ContestHandler
from .handlers.counter import CounterHandler
from .handlers.compare import CompareHandler
from .handlers.evaluators import EvaluatorsHandler
from .handlers.modify import ModifyHandler
from .handlers.manage import ManageHandler
from .handlers.graph import GraphHandler


def get_contest_from_request(request):
    contest_name_id = request.GET.get('contest')
    if not contest_name_id:
        return False
    return get_object_or_404(Contest, name_id=contest_name_id)

def check_evaluator_permission(request, contest):
    try:
        Evaluator.objects.get(contest=contest, profile=request.user.profile, user_status__in=['A', 'G'])
    except Evaluator.DoesNotExist:
        raise PermissionDenied("You are not allowed to access this page.")

def contest_evaluator_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        contest = get_contest_from_request(request)
        if not contest:
            raise BadRequest("Contest not found.")
        check_evaluator_permission(request, contest)
        return view_func(request, contest, *args, **kwargs)
    return _wrapped_view

def render_with_bidi(request, template_name, context):
    bidi_context = {
        'right': 'left' if translation.get_language_bidi() else 'right',
        'left': 'right' if translation.get_language_bidi() else 'left',
    }
    context.update(bidi_context)
    return render(request, template_name, context)

def get_head_ref():
    git_dir = Path('.') / '.git'
    head_file = git_dir / 'HEAD'
    with head_file.open('r') as f:
        ref = f.readline().strip()
    
    if ref.startswith('ref:'):
        ref_path = ref.split(' ')[1]
        commit_file = git_dir / ref_path
    else:
        commit_file = None
    
    return commit_file, ref

def get_active_branch_name():
    commit_file, ref = get_head_ref()
    if commit_file:
        return ref.partition("refs/heads/")[2]
    return "Detached HEAD"

def get_active_commit_hash():
    commit_file, ref = get_head_ref()
    if commit_file and commit_file.exists():
        with commit_file.open('r') as f:
            return f.readline().strip()[:7]
    return ref[:7]

def get_active_commit_message():
    commit_file, ref = get_head_ref()
    if commit_file and commit_file.exists():
        with commit_file.open('r') as f:
            commit_hash = f.readline().strip()
    else:
        commit_hash = ref

    git_dir = Path('.') / '.git'
    commit_object = git_dir / 'objects' / commit_hash[:2] / commit_hash[2:]
    if commit_object.exists():
        with commit_object.open('rb') as f:
            compressed_data = f.read()
        decompressed_data = zlib.decompress(compressed_data).decode('utf-8', errors='ignore')
        commit_message = decompressed_data.split('\n\n', 1)[-1].strip()
        return commit_message
    return "No commit message found"

@require_GET
def redirect_view(request):
    lang = request.GET.get('lang')
    contest = request.GET.get('contest')
    page = request.GET.get('page')

    page_list = [
        'contest', 
        'triage', 
        'counter', 
        'backtrack', 
        'compare', 
        'edits', 
        'evaluators', 
        'modify',
        'graph',
    ]

    if contest and not page:
        response = redirect(f"/contests/?contest={contest}")
    elif contest and page in page_list:
        response = redirect(f"/{page}/?contest={contest}")
    else:
        response = redirect('/')

    if lang:
        translation.activate(lang)
        response.set_cookie(settings.LANGUAGE_COOKIE_NAME, lang)

    return response

@require_GET
def home_view(request):
    contests = Contest.objects.select_related('group').order_by('-start_time')
    
    contests_chooser = {}
    for contest in contests:
        group = contest.group.name
        if group not in contests_chooser:
            contests_chooser[group] = []
        contests_chooser[group].append([contest.name_id, contest.name])
    contests_groups = list(contests_chooser.keys())

    return render_with_bidi(request, 'home.html', {
        'contests_groups': contests_groups,
        'contests_chooser': contests_chooser,
        'git_branch': 'Branch: ' + get_active_branch_name(),
        'git_commit': 'Commit: ' + get_active_commit_hash() + ' - ' + get_active_commit_message(),
    })

@require_GET
def contest_view(request):
    contest = get_contest_from_request(request)
    if not contest:
        return redirect('/')
    handler = ContestHandler(contest=contest)
    return render_with_bidi(request, 'contest.html', handler.execute(request))

@require_GET
def graph_view(request):
    contest = get_contest_from_request(request)
    if not contest:
        return redirect('/')
    handler = GraphHandler(contest=contest)
    return render_with_bidi(request, 'graph.html', handler.execute())

@login_required()
@contest_evaluator_required
@require_http_methods(["GET", "POST"])
def triage_view(request, contest):
    handler = TriageHandler(contest=contest, user=request.user, api_endpoint=contest.api_endpoint)
    if request.method == 'POST':
        do_evaluate = handler.do_evaluate(request)
    else:
        do_evaluate = {'action': None}
    get_evaluate = handler.get_evaluate(request)

    # Ensure safe dict merge even if handler returns None
    if not isinstance(do_evaluate, dict):
        do_evaluate = {}
    if not isinstance(get_evaluate, dict):
        get_evaluate = {}
    triage_dict = get_evaluate | do_evaluate
    triage_dict.update({
        'triage_points': int(contest.max_bytes_per_article / contest.bytes_per_points),
        'evaluator_status': Evaluator.objects.get(contest=contest, profile=request.user.profile).user_status,
    })
    return render_with_bidi(request, "triage.html", triage_dict)

@login_required()
@contest_evaluator_required
@require_http_methods(["GET", "POST"])
def counter_view(request, contest):
    handler = CounterHandler(contest=contest)
    return render_with_bidi(request, "counter.html", handler.get_context(request))

@login_required()
@contest_evaluator_required
@require_http_methods(["GET", "POST"])
def backtrack_view(request, contest):
    qualified = False
    diff = None
    if request.POST.get('diff'):
        diff = request.POST.get('diff')
        evaluator = Evaluator.objects.get(contest=contest, profile=request.user.profile)
        new_qualification = Qualification.objects.create(contest=contest, diff=Edit.objects.get(diff=diff), evaluator=evaluator)
        qualified = Edit.objects.filter(contest=contest, diff=diff, last_qualification__isnull=True).update(last_qualification=new_qualification)

    edits = Edit.objects.filter(
        contest=contest, 
        last_qualification__isnull=True, 
        participant__isnull=False
    ).order_by('participant__user', 'timestamp')

    result = defaultdict(lambda: {'enrollment_timestamp': None, 'diffs': []})
    for edit in edits:
        user = edit.participant.user
        result[user]['enrollment_timestamp'] = edit.participant.timestamp
        result[user]['diffs'].append({'diff': edit.diff, 'bytes': edit.orig_bytes, 'timestamp': edit.timestamp})

    return render_with_bidi(request, 'backtrack.html', {
        'contest': contest,
        'result': result.items(),
        'diff': diff if qualified else None
    })

@login_required()
@contest_evaluator_required
@require_http_methods(["GET", "POST"])
def compare_view(request, contest):
    handler = CompareHandler(contest=contest)
    return render_with_bidi(request, 'compare.html', handler.execute(request))

@login_required()
@contest_evaluator_required
@require_http_methods(["GET", "POST"])
def edits_view(request, contest):
    edits = Edit.objects.filter(contest=contest).select_related(
        'article', 'participant', 'last_evaluation__evaluator__profile', 'last_qualification'
    )

    if request.POST.get('csv'):
        response = HttpResponse(content_type="text/csv; charset=utf-8",
                                headers={"Content-Disposition": 'attachment; filename="edits.csv"'})
        response.write(loader.get_template("edits.txt").render({'data': edits}))
        return response

    return render_with_bidi(request, 'edits.html', {'contest': contest, 'edits': edits})

@login_required()
@contest_evaluator_required
@require_http_methods(["GET", "POST"])
def evaluators_view(request, contest):
    handler = EvaluatorsHandler(contest=contest)
    return render_with_bidi(request, 'evaluators.html', handler.execute(request))

@login_required()
@contest_evaluator_required
@require_http_methods(["GET", "POST"])
def modify_view(request, contest):
    handler = ModifyHandler(contest=contest)
    return render_with_bidi(request, 'modify.html', handler.execute(request))

@login_required()
@require_http_methods(["GET", "POST"])
def manage_view(request):
    if request.user.profile.group_set.exists():
        handler = ManageHandler()
        return render_with_bidi(request, 'manage.html', handler.execute(request))
    raise PermissionDenied("You are not allowed to access this page.")