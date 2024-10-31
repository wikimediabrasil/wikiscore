from django.shortcuts import render
from django.utils import timezone
from contests.models import Contest, Edit, Evaluator, Participant
from django.shortcuts import render, redirect, get_object_or_404
from datetime import timezone as dt_timezone

class CounterHandler:
    def __init__(self, contest):
        self.contest = contest

    def get_points(self, time_round):
        query = f"""
        SELECT 
            `user_table`.`user_id` AS `id`, 
            `user_table`.`user`, 
            IFNULL(`points`.`sum`, 0) AS `sum`, 
            IFNULL(`points`.`total edits`, 0) AS `total_edits`, 
            IFNULL(`points`.`bytes points`, 0) AS `bytes_points`, 
            IFNULL(`points`.`total pictures`, 0) AS `total_pictures`, 
            IFNULL(`points`.`pictures points`, 0) AS `pictures_points`, 
            IFNULL(`points`.`total points`, 0) AS `total_points` 
        FROM (
            SELECT 
                DISTINCT `contests_edit`.`user_id`, 
                `contests_participant`.`user` 
            FROM 
                `contests_edit` 
            INNER JOIN `contests_participant` ON `contests_participant`.`local_id` = `contests_edit`.`user_id`
            WHERE
                `contests_edit`.`contest_id` = '{self.contest.id}'
                AND `contests_participant`.`contest_id` = '{self.contest.id}'
        ) AS `user_table` 
        LEFT JOIN (
            SELECT 
                t1.`user_id`, 
                t1.`sum`, 
                t1.`total edits`, 
                t1.`bytes points`, 
                t2.`total pictures`, 
                t2.`pictures points`, 
                (t1.`bytes points` + t2.`pictures points`) AS `total points` 
            FROM (
                SELECT 
                    edits_ruled.`user_id`, 
                    SUM(edits_ruled.`bytes`) AS `sum`, 
                    SUM(edits_ruled.`valid_edits`) AS `total edits`, 
                    FLOOR(SUM(edits_ruled.`bytes`) / edits_ruled.`bytes_per_points`) AS `bytes points` 
                FROM (
                    SELECT 
                        `contests_edit`.`article_id`, 
                        `contests_edit`.`user_id`, 
                        CASE 
                            WHEN SUM(`contests_evaluation`.`real_bytes`) > `contests_contest`.`max_bytes_per_article` 
                            THEN `contests_contest`.`max_bytes_per_article` 
                            ELSE SUM(`contests_evaluation`.`real_bytes`) 
                        END AS `bytes`, 
                        COUNT(`contests_evaluation`.`valid_edit`) AS `valid_edits`, 
                        `contests_contest`.`bytes_per_points` AS `bytes_per_points` 
                    FROM 
                        `contests_edit` 
                        LEFT JOIN `contests_evaluation` ON `contests_edit`.`last_evaluation_id` = `contests_evaluation`.`id` 
                        LEFT JOIN `contests_contest` ON `contests_edit`.`contest_id` = `contests_contest`.`id` 
                    WHERE 
                        `contests_edit`.`contest_id` = '{self.contest.id}' 
                        AND `contests_evaluation`.`valid_edit` = '1' 
                        AND `contests_edit`.`timestamp` < '{time_round}'
                    GROUP BY 
                        `contests_edit`.`user_id`, 
                        `contests_edit`.`article_id`
                ) AS edits_ruled 
                GROUP BY 
                    edits_ruled.`user_id`
            ) AS `t1` 
            LEFT JOIN (
                SELECT 
                    `distinct`.`user_id`, 
                    `distinct`.`article_id`, 
                    SUM(`distinct`.`pictures`) AS `total pictures`, 
                    CASE 
                        WHEN `distinct`.`pictures_per_points` = 0 
                        THEN 0 
                        ELSE FLOOR(SUM(`distinct`.`pictures`) / `distinct`.`pictures_per_points`) 
                    END AS `pictures points` 
                FROM (
                    SELECT 
                        `contests_edit`.`user_id`, 
                        `contests_edit`.`article_id`, 
                        `contests_evaluation`.`pictures`, 
                        `contests_edit`.`id`, 
                        `contests_contest`.`pictures_per_points` 
                    FROM 
                        `contests_edit` 
                    LEFT JOIN `contests_evaluation` ON `contests_edit`.`last_evaluation_id` = `contests_evaluation`.`id` 
                    LEFT JOIN `contests_contest` ON `contests_edit`.`contest_id` = `contests_contest`.`id` 
                    WHERE 
                        `contests_edit`.`contest_id` = '{self.contest.id}' 
                        AND `contests_evaluation`.`pictures` IS NOT NULL 
                        AND `contests_edit`.`timestamp` < '{time_round}' 
                    GROUP BY 
                        CASE 
                            WHEN `contests_contest`.`pictures_mode` = 0 
                            THEN `contests_edit`.`user_id` 
                        END, 
                        CASE 
                            WHEN `contests_contest`.`pictures_mode` = 0 
                            THEN `contests_edit`.`article_id` 
                        END, 
                        CASE 
                            WHEN `contests_contest`.`pictures_mode` = 0 
                            THEN `contests_evaluation`.`pictures` 
                            ELSE `contests_edit`.`id` END
                ) AS `distinct` 
                GROUP BY 
                    `distinct`.`user_id`
            ) AS `t2` ON t1.`user_id` = t2.`user_id`
        ) AS `points` ON `user_table`.`user_id` = `points`.`user_id` 
        ORDER BY 
            `points`.`total points` DESC, 
            `points`.`sum` DESC, 
            `user_table`.`user` ASC;
        """

        counter = Edit.objects.raw(query)
        return counter

    def get_context(self, request):
        if request.POST.get('time_round'):
            time_round_str = request.POST.get('time_round')
            try:
                request_time = timezone.datetime.strptime(time_round_str, '%Y-%m-%dT%H:%M:%S')
            except ValueError:
                request_time = timezone.datetime.strptime(time_round_str, '%Y-%m-%dT%H:%M')
            request_time = request_time.replace(tzinfo=dt_timezone.utc)
        else:
            request_time = timezone.now()

        time_round = request_time.strftime('%Y-%m-%d %H:%M:%S')

        counter = self.get_points(time_round)

        manager = True if Evaluator.objects.get(
            contest=self.contest, 
            profile=request.user.profile
        ).user_status == 'G' else False

        if request.method == 'POST':
            success = self.reset_participant(request)
        else:
            success = False

        return {
            'contest': self.contest,
            'counter': counter,
            'date': request_time.strftime('%Y-%m-%d'),
            'time': request_time.strftime('%H:%M:%S'),
            'time_form': request_time.strftime('%Y-%m-%dT%H:%M:%S'),
            'contest_begun': self.contest.start_time < request_time,
            'manager': manager,
            'success': success,
        }

    def reset_participant(self, request):
        participant_id = request.POST.get('user_id')
        participant = Edit.objects.filter(
            contest=self.contest, 
            participant=Participant.objects.get(contest=self.contest, local_id=participant_id)
        ).update(last_evaluation=None)
        return True if participant.count() > 0 else False
    
