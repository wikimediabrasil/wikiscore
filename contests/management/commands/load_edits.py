import requests
import time
from datetime import datetime
from django.core.management.base import BaseCommand
from django.db import connection
from contests.models import Contest, Article, Edit, Participant

class Command(BaseCommand):
    help = "Carrega edições para o concurso."

    def add_arguments(self, parser):
        parser.add_argument('contest', type=str, help="Nome ID do concurso")

    def handle(self, *args, **options):
        contest_name_id = options.get('contest')
        contest = Contest.objects.get(name_id=contest_name_id)

        # Coleta lista de artigos na categoria ou via PetScan
        if contest.category_petscan:
            # Recupera lista do PetScan
            petscan_list = requests.get(f"https://petscan.wmflabs.org/?format=json&psid={contest.category_petscan}").json()
            list_ = [
                {"id": item['id'], "title": item['title']} 
                for item in petscan_list['*'][0]['a']['*']
            ]
        else:
            # Coleta lista de artigos na categoria
            list_ = self.get_category_articles(contest)

        # Desativa lista de artigos já existentes
        Article.objects.filter(contest=contest).update(active=False)

        # Insere lista de artigos na tabela
        # Se já existir, apenas ativa
        for item in list_:
            article, created = Article.objects.get_or_create(
                contest=contest,
                articleID=item['pageid'],
            )
            if not created:
                article.active = True
                article.save(update_fields=['active'])
            if article.title == '' or article.title != item['title']:
                article.title = item['title']
                article.save(update_fields=['title'])

        # Coleta lista de revisões já inseridas no banco de dados
        existing_revisions = Edit.objects.filter(contest=contest).values_list('diff', flat=True)

        # Loop para análise de cada artigo
        for article in Article.objects.filter(contest=contest):
            self.stdout.write(f"CurID: {article.articleID}")

            # Coleta revisões do artigo
            revisions = self.get_article_revisions(article, contest)

            # Verifica se o artigo possui revisões dentro dos parâmetros escolhidos
            if not revisions:
                continue

            # Loop para cada revisão do artigo
            for revision in revisions:
                self.stdout.write(f"- Diff: {revision['revid']}")
                if revision['revid'] in existing_revisions:
                    continue
                self.stdout.write(" -> inserindo")

                # Coleta dados de diferenciais da revisão
                compare_data = self.get_revision_compare(revision, contest)

                # Executa inserção no banco de dados
                Edit.objects.create(
                    diff=revision['revid'],
                    article=article,
                    timestamp=compare_data.get('timestamp'),
                    user_id=compare_data.get('user_id'),
                    orig_bytes=compare_data.get('bytes'),
                    new_page=compare_data.get('new_page'),
                    contest=contest
                )

                self.stdout.write(" -> feito!")

        self.stdout.write("<br>Concluido! (1/3)<br>")

    def get_category_articles(self, contest):
        """Coleta lista de artigos na categoria."""
        list_ = {}
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
            
        list_.update(response['query']['pages'])

        # Coleta segunda página da lista, caso exista
        while 'continue' in response:
            categorymembers_api_params['gcmcontinue'] = response['continue']['gcmcontinue']
            response = requests.get(contest.api_endpoint, params=categorymembers_api_params).json()
            list_.update(response['query']['pages'])

        for page in list_.values():
            if page.get('subjectid'):
                pages.append({
                    "pageid": page.get('subjectid'),
                    "title": page.get('associatedpage'),
                })

        return pages

    def get_article_revisions(self, article, contest):
        """Coleta revisões do artigo."""
        revisions_api_params = {
            "action": "query",
            "format": "json",
            "prop": "revisions",
            "rvprop": "ids",
            "rvlimit": "max",
            "rvstart": contest.end_time.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
            "rvend": contest.start_time.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
            "pageids": article.articleID
        }
        revisions_api = requests.get(contest.api_endpoint, params=revisions_api_params).json()
        revisions_api = revisions_api.get('query', {}).get('pages', {}).get(str(article.articleID), {})

        return revisions_api.get('revisions', [])

    def get_revision_compare(self, revision, contest):
        """Coleta dados de diferenciais da revisão."""
        compare_api_params = {
            "action": "compare",
            "format": "json",
            "torelative": "prev",
            "prop": "diffsize|size|title|user|timestamp",
            "fromrev": revision['revid']
        }
        compare_api = requests.get(contest.api_endpoint, params=compare_api_params).json()

        if 'compare' not in compare_api:
            return {"timestamp": None, "user_id": None, "bytes": None, "new_page": None}

        compare_api = compare_api['compare']

        # Verifica se página é nova
        if 'fromsize' not in compare_api:
            compare_api['new_page'] = True
        else:
            compare_api['new_page'] = False
            compare_api['tosize'] = compare_api['tosize'] - compare_api['fromsize']

        return {
            "timestamp": compare_api.get('totimestamp'),
            "user_id": compare_api.get('touserid'),
            "bytes": compare_api.get('tosize'),
            "new_page": compare_api.get('new_page')
        }

