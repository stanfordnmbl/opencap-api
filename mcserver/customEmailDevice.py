from django_otp.plugins.otp_email.models import EmailDevice
from django.core.mail import send_mail
from django.utils.html import strip_tags
from django.conf import settings
from django.template import Template, Context
from django.template.loader import get_template


class CustomEmailDevice(EmailDevice):

    def generate_challenge(self, extra_context=None):
        """
        Generates a random token and emails it to the user.
        :param extra_context: Additional context variables for rendering the
            email template.
        :type extra_context: dict
        """
        self.generate_token(valid_secs=settings.OTP_EMAIL_TOKEN_VALIDITY)

        context = {'token': self.token, **(extra_context or {})}
        if settings.OTP_EMAIL_BODY_TEMPLATE:
            body = Template(settings.OTP_EMAIL_BODY_TEMPLATE).render(Context(context))
        else:
            body = get_template(settings.OTP_EMAIL_BODY_TEMPLATE_PATH).render(context)

        send_mail(settings.OTP_EMAIL_SUBJECT,
                  strip_tags(body),
                  settings.OTP_EMAIL_SENDER,
                  [self.email or self.user.email],
                  html_message=body)

        message = "sent by email"

        return message