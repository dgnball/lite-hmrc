import datetime
import time

from background_task.models import Task
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.status import HTTP_200_OK, HTTP_503_SERVICE_UNAVAILABLE
from rest_framework.views import APIView

from conf.settings import LITE_LICENCE_UPDATE_POLL_INTERVAL, INBOX_POLL_INTERVAL, EMAIL_AWAITING_REPLY_TIME
from mail.enums import ReceptionStatusEnum, ReplyStatusEnum
from mail.models import Mail
from mail.tasks import LICENCE_UPDATES_TASK_QUEUE, MANAGE_INBOX_TASK_QUEUE


class HealthCheck(APIView):
    def get(self, request):
        """
        Provides a health check endpoint as per [https://man.uktrade.io/docs/howtos/healthcheck.html#pingdom]
        """

        start_time = time.time()

        # If no licence update task is scheduled to run in the next LITE_LICENCE_UPDATE_POLL_INTERVAL seconds
        licence_update_task = Task.objects.filter(
            queue=LICENCE_UPDATES_TASK_QUEUE,
            run_at__lte=timezone.now() + datetime.timedelta(seconds=LITE_LICENCE_UPDATE_POLL_INTERVAL),
        )
        if not licence_update_task.exists():
            return self._build_response(self._get_response_time(start_time), "not OK", HTTP_503_SERVICE_UNAVAILABLE)

        # If no inbox task is scheduled to run in the next INBOX_POLL_INTERVAL seconds
        manage_inbox_task = Task.objects.filter(
            queue=MANAGE_INBOX_TASK_QUEUE, run_at__lte=timezone.now() + datetime.timedelta(seconds=INBOX_POLL_INTERVAL)
        )
        if not manage_inbox_task.exists():
            return self._build_response(self._get_response_time(start_time), "not OK", HTTP_503_SERVICE_UNAVAILABLE)

        # If an email has been rejected
        rejected_email = Mail.objects.filter(
            status=ReceptionStatusEnum.REPLY_SENT, response_data__icontains=ReplyStatusEnum.REJECTED,
        )
        if rejected_email.exists():
            return self._build_response(self._get_response_time(start_time), "not OK", HTTP_503_SERVICE_UNAVAILABLE)

        # If an email has been awaiting for a reply for longer than EMAIL_AWAITING_REPLY_TIME seconds
        email_awaiting_response_for_prolonged_period_of_time = Mail.objects.filter(
            status=ReceptionStatusEnum.REPLY_PENDING,
            sent_at__lte=timezone.now() - datetime.timedelta(seconds=EMAIL_AWAITING_REPLY_TIME),
        )
        if email_awaiting_response_for_prolonged_period_of_time.exists():
            return self._build_response(self._get_response_time(start_time), "not OK", HTTP_503_SERVICE_UNAVAILABLE)

        return self._build_response(self._get_response_time(start_time), "OK", HTTP_200_OK)

    @classmethod
    def _get_response_time(cls, start_time) -> str:
        duration_ms = (time.time() - start_time) * 1000
        return "{:.3f}".format(duration_ms)

    @classmethod
    def _get_xml(cls, status, response_time):
        return f"""
                   <pingdom_http_custom_check>
                     <status>{status}</status> 
                     <response_time>{response_time}</response_time>
                   </pingdom_http_custom_check>
                """

    @classmethod
    def _build_response(cls, response_time, message, status) -> HttpResponse:
        return HttpResponse(
            content=cls._get_xml(message, response_time), content_type="application/xml", status=status,
        )
