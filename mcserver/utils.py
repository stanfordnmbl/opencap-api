from django.conf import settings
from django.template.loader import render_to_string


def send_otp_challenge(user):
    from mcserver.customEmailDevice import CustomEmailDevice
    device = user.emaildevice_set.all()[0]
    device.__class__ = CustomEmailDevice

    # Get template from path and set variables. The {{token}}
    # is then substituted by the device by the real token.
    settings.OTP_EMAIL_BODY_TEMPLATE = render_to_string(
        settings.OTP_EMAIL_BODY_TEMPLATE_PATH) % (settings.LOGO_LINK, "{{token}}")

    # Set subject here, so everything is together.
    settings.OTP_EMAIL_SUBJECT = "Opencap - Verification Code"

    device.generate_challenge()
    print("CHALLENGE SENT")

