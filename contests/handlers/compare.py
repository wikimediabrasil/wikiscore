from django.shortcuts import render
from django.utils import timezone
from datetime import timedelta
import requests
from contests.models import Contest, Edit, Qualification, Evaluator, Article

class CompareHandler:    
    def __init__(self, contest):
        self.contest = contest
        self.update = False

    def execute(self, request):
        """Handle the request."""
        contest = self.contest
        return_dict = {'contest': contest }
        update_request = False
        early_update = self.check_recent_update(contest)

        if request.method == 'POST':
            if request.POST.get('update') and not early_update:
                self.call_update(contest)
                update_request = True
            if request.POST.get('diff'):
                self.fix_inconsistent_edit(contest, request.POST.get('diff'))

        return_dict.update({
            'inconsistent_edits': self.get_inconsistent_edits(contest),
            'reverted_edits': self.get_reverted_edits(contest),
            'update_countdown': self.get_update_countdown(contest),
            'early_update': early_update,
            'update_request': update_request,
        })

        if contest.official_list_pageid and contest.category_pageid:
            return_dict.update({'articles': self.generate_list_cat_intersection(contest)})
        else:
            return_dict.update({
                'articles': {
                    'list_wikidata': [], 
                    'list_official_not_category': [], 
                    'list_category_not_official': []
                },
            })
        
        if contest.api_endpoint == 'https://pt.wikipedia.org/w/api.php':
            return_dict['articles'].update({'deletion': self.get_deletion_pages(contest)})
        else:
            return_dict['articles'].update({'deletion': []})

        return return_dict
    
    def generate_list_cat_intersection(self, contest):
        """Gera lista de artigos que estão tanto na lista oficial quanto na categoria."""
        list_official = [page['title'] for page in self.get_list_articles(contest).values() if 'missing' not in page]

        category = self.get_category_articles(contest)
        list_category = [page['title'] for page in category.values()]
        list_wikidata = [page['title'] for page in category.values() if 'pageprops' not in page or 'wikibase_item' not in page['pageprops']]

        list_category_not_official = list(set(list_official) - set(list_category))
        list_official_not_category = list(set(list_category) - set(list_official))
        
        return {
            'list_wikidata': list_wikidata,
            'list_official_not_category': list_official_not_category,
            'list_category_not_official': list_category_not_official,
        }


    def get_list_articles(self, contest):
        """Coleta lista de artigos na lista oficial."""
        
        list_ = {}
        list_api_params = {
            'action': 'query',
            'format': 'json',
            'generator': 'links',
            'pageids': contest.official_list_pageid,
            'gplnamespace': '0',
            'gpllimit': 'max',
        }
        response = requests.get(contest.api_endpoint, params=list_api_params).json()
        if 'query' not in response:
            return list_

        list_.update(response['query']['pages'])

        while 'continue' in response:
            list_api_params['gplcontinue'] = response['continue']['gplcontinue']
            response = requests.get(contest.api_endpoint, params=list_api_params).json()
            list_.update(response['query']['pages'])

        return list_

    def get_category_articles(self, contest):
        """Coleta lista de artigos na categoria."""
        list_ = []
        pages = []
        categorymembers_api_params = {
            "action": "query",
            "format": "json",
            "prop": "info",
            "generator": "categorymembers",
            "inprop": "associatedpage|subjectid",
            "gcmnamespace": "1",
            "gcmpageid": contest.category_pageid,
            "gcmprop": "ids|title",
            "gcmlimit": "max",

        }
        response = requests.get(contest.api_endpoint, params=categorymembers_api_params).json()
        if 'query' not in response:
            return list_
            
        list_.extend(response['query']['pages'])

        # Coleta segunda página da lista, caso exista
        while 'continue' in response:
            categorymembers_api_params['gcmcontinue'] = response['continue']['gcmcontinue']
            response = requests.get(contest.api_endpoint, params=categorymembers_api_params).json()
            list_.extend(response['query']['pages'])

        for page in list_.values():
            pages.append({
                "pageid": page['subjectid'],
                "title": page['associatedpage'],
            })

        # Divide "pages" em grupos de, no máximo, 50 itens. Depois, processa a coleta de itens do Wikidata para cada grupo.
        # Isso é necessário porque a API do Wikidata não aceita mais de 50 itens por requisição.
        list_category = []
        for i in range(0, len(pages), 50):
            pageids = '|'.join([str(page['pageid']) for page in pages[i:i+50]])
            category_api_params = {
                "action": "query",
                "format": "json",
                "prop": "pageprops",
                "ppprop": "wikibase_item",
                "pageids": pageids,
            }
            response = requests.get(contest.api_endpoint, params=category_api_params).json()
            list_category.extend(response['query']['pages'])

        # Adiciona cada "pageprops" ao seu respectivo objeto em "pages"
        for page in list_category:
            for p in pages:
                if p['pageid'] == page['pageid']:
                    p.update(page)

        return pages


    def get_deletion_pages(self, contest):
        """Coleta páginas marcadas para eliminação."""
        list_ = []
        deletion_api_params = {
            'action': 'query',
            'format': 'json',
            'list': 'categorymembers',
            'cmpageid': 1001045,
            'cmnamespace': '4',
            'cmlimit': 'max',
            'cmprop': 'title',
        }
        response = requests.get(contest.api_endpoint, params=deletion_api_params).json()
        if 'query' not in response:
            return list_
            
        list_.extend(response['query']['categorymembers'])

        while 'continue' in response:
            deletion_api_params['cmcontinue'] = response['continue']['cmcontinue']
            response = requests.get(contest.api_endpoint, params=deletion_api_params).json()
            list_.extend(response['query']['categorymembers'])

        articles = [page['title'][32:] for page in list_]

        cats_ = []
        cats = [3501865, 2419924]
        for cat in cats:
            cats_api_params = {
                'action': 'query',
                'format': 'json',
                'list': 'categorymembers',
                'cmpageid': cat,
                'cmnamespace': '0',
                'cmlimit': 'max',
                'cmprop': 'title',
            }
            response = requests.get(contest.api_endpoint, params=cats_api_params).json()
            cats_.extend(response['query']['categorymembers'])

            while 'continue' in response:
                deletion_api_params['cmcontinue'] = response['continue']['cmcontinue']
                response = requests.get(contest.api_endpoint, params=deletion_api_params).json()
                cats_.extend(response['query']['categorymembers'])

            articles.extend([page['title'] for page in cats_])

        articles = list(dict.fromkeys(articles))
        cat = [word.replace('_', ' ') for word in Article.objects.filter(contest=contest).values_list('title', flat=True)]
        intersect = list(set(articles) & set(cat))
        return intersect

    def fix_inconsistent_edit(self, contest, diff):
        """Corrige edições inconsistentes."""
        qualif = Qualification.objects.create(
            contest=contest,
            status='0',
            diff=Edit.objects.get(contest=contest, diff=diff),
            evaluator=Evaluator.objects.get(contest=contest, profile=self.user.profile),
        )
        Edit.objects.filter(contest=contest, diff=diff).update(last_qualification=qualif)

    def get_inconsistent_edits(self, contest):
        """Coleta edições inconsistentes."""
        query = Edit.objects.filter(
            contest=contest,
            article__active=False,
            last_qualification__status='1',
        )
        return query

    def get_reverted_edits(self, contest):
        """Coleta edições revertidas e validadas."""
        query = Edit.objects.filter(
            contest=contest,
            last_qualification__status='0',
            last_evaluation__valid_edit=True,
        )
        return query

    def get_update_countdown(self, contest):
        """Coleta contagem regressiva para atualização."""
        if contest.end_time + timedelta(days=2) < timezone.now():
            return False
        elif contest.next_update is None:
            return 0
        elif contest.next_update > timezone.now() and not self.update:
            return (contest.next_update - timezone.now()).total_seconds()
        else:
            return 0

    def call_update(self, contest):
        """Chama atualização."""
        Contest.objects.filter(name_id=contest.name_id).update(next_update=None)
        self.update = True

    def check_recent_update(self, contest):
        """Verifica se houve atualização recente."""
        # Caso todas as variáveis estejam nulas, retorna False
        if contest.started_update is None and contest.finished_update is None and contest.next_update is None:
            return False
        
        # Caso a atualização tenha sido iniciada e terminada, mas não há próxima atualização definida, retorna False
        if contest.started_update is not None and contest.finished_update is not None and contest.next_update is None:
            return False

        # Se a atualização foi iniciada, mas ainda não foi terminada ou terminou há menos de 30 minutos
        if contest.finished_update is None or contest.finished_update < contest.started_update or (timezone.now() - contest.finished_update) < timedelta(minutes=30):
            return True

        # Caso contrário, não há atualização em andamento ou recente
        return False
    