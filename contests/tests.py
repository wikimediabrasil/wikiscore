from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from contests.models import (
    Article,
    Contest,
    Edit,
    EditWikidata,
    Group,
)
from credentials.models import CustomUser, Profile


class EditWikidataModelTests(TestCase):
    def setUp(self):
        self.group = Group.objects.create(name="wikidata-testers")
        self.user = CustomUser.objects.create(username="tester")
        self.profile = Profile.objects.create(
            global_id="global-1",
            username="tester",
            account=self.user,
        )
        self.contest = Contest.objects.create(
            name_id="wd-test",
            start_time=timezone.now() - timedelta(days=1),
            end_time=timezone.now() + timedelta(days=1),
            name="Wikidata Test Contest",
            endpoint="https://www.wikidata.org/wiki/",
            api_endpoint="https://www.wikidata.org/w/api.php",
            official_list_pageid=1,
            theme="default",
            group=self.group,
        )

    def _make_edit(self, diff=100):
        return Edit.objects.create(
            contest=self.contest,
            diff=diff,
            article=Article.objects.create(
                contest=self.contest,
                articleID=diff,
                title=f"Q{diff}",
            ),
            timestamp=timezone.now(),
            user_id=1,
            orig_bytes=10,
            new_page=False,
        )

    def test_editwikidata_is_created_with_defaults(self):
        edit = self._make_edit(diff=100)
        wd = EditWikidata.objects.create(edit=edit)
        self.assertEqual(wd.statements_created, 0)
        self.assertEqual(wd.statements_modified, 0)
        self.assertEqual(wd.references_created, 0)
        self.assertEqual(wd.references_modified, 0)
        self.assertEqual(wd.qualifiers_created, 0)
        self.assertEqual(wd.qualifiers_modified, 0)

    def test_editwikidata_reverse_relation(self):
        edit = self._make_edit(diff=102)
        wd = EditWikidata.objects.create(
            edit=edit,
            statements_created=8,
            references_modified=9,
        )
        self.assertEqual(edit.editwikidata, wd)
        self.assertEqual(edit.editwikidata.statements_created, 8)
        self.assertEqual(edit.editwikidata.references_modified, 9)

    def test_str_representation(self):
        edit = self._make_edit(diff=106)
        wd = EditWikidata.objects.create(edit=edit)
        self.assertIn("wd-test", str(wd))
        self.assertIn(str(edit.diff), str(wd))

    def test_create_edit_and_editwikidata_together(self):
        edit = self._make_edit(diff=107)
        wd = EditWikidata.objects.create(
            edit=edit,
            statements_created=10,
            statements_modified=11,
            references_created=12,
            references_modified=13,
            qualifiers_created=14,
            qualifiers_modified=15,
        )
        self.assertEqual(edit.editwikidata.statements_created, 10)
        self.assertEqual(edit.editwikidata.qualifiers_modified, 15)
        self.assertEqual(wd.edit, edit)
