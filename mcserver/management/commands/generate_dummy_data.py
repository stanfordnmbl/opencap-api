from django.core.management.base import BaseCommand
import random


class Command(BaseCommand):
    def handle(self, *args, **options):
        from mcserver.models import User, Subject, Session, Trial, Result
        user = User.objects.get(id=1)

        for i in range(50, 1000):
            subject = Subject.objects.create(
                name=f"Subject {i}",
                user=user,
                weight=random.randint(50, 100),
                height=random.randint(150, 200),
                age=random.randint(18, 60),
                birth_year=random.randint(1960, 2000),
                gender=random.choice(["man", "woman"]),
                sex_at_birth=random.choice(["man", "woman"]),
            )

        subjects = list(Subject.objects.all())
        for j in range(50, 1000):
            session = Session.objects.create(
                user=user,
                subject=subjects[50-j],
                public=random.choice([True, False]),
                meta={"settings": {"framerate": "60", "posemodel": "openpose", "datasharing": "Share processed data and identified videos"}, "checkerboard": {"cols": "5", "rows": "4", "placement": "backWall", "square_size": "35"}},
            )
            for k in range(5):
                Trial.objects.create(
                    session=session,
                    status='done',
                    name=f"trial_{j}_{k}",
                )
            Trial.objects.create(session=session, status='done', name='neutral')
