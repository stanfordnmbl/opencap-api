import time
import threading
from unittest.mock import patch

from django.test import TransactionTestCase
from django.db import connection
from django.urls import reverse, NoReverseMatch
from rest_framework.test import APIClient

from mcserver.models import Trial, Session
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group


class DequeueConcurrencyTest(TransactionTestCase):
    def setUp(self):
        User = get_user_model()

        # 1. Setup mock data and permissions
        self.user = User.objects.create(
            username="worker_test",
            is_staff=True,
            is_superuser=True
        )

        backend_group, _ = Group.objects.get_or_create(name="backend")
        admin_group, _ = Group.objects.get_or_create(name="admin")
        self.user.groups.add(backend_group, admin_group)

        self.session = Session.objects.create(user=self.user, isMono=False)

        # 2. Create valid trials
        self.trial_1 = Trial.objects.create(
            session=self.session,
            name="calibration",
            status="stopped",
            result=None
        )
        self.trial_2 = Trial.objects.create(
            session=self.session,
            name="calibration",
            status="stopped",
            result=None
        )

        # 3. Dynamically resolve the URL to guarantee we hit the right endpoint
        try:
            self.dequeue_url = reverse('trial-dequeue')
        except NoReverseMatch:
            try:
                self.dequeue_url = reverse('trials-dequeue')
            except NoReverseMatch:
                self.dequeue_url = '/api/trials/dequeue/'

        print(f"\n[DEBUG] Using dequeue URL: {self.dequeue_url}")

    def test_concurrent_dequeue_skips_locked_rows(self):
        client1 = APIClient()
        client2 = APIClient()

        client1.force_authenticate(user=self.user)
        client2.force_authenticate(user=self.user)

        results = {}
        thread1_locked = threading.Event()

        def worker_1():
            original_save = Trial.save

            def delayed_save(self_instance, *args, **kwargs):
                thread1_locked.set()
                time.sleep(1.5)  # Hold the lock slightly longer
                return original_save(self_instance, *args, **kwargs)

            try:
                with patch('mcserver.models.Trial.save', new=delayed_save):
                    response = client1.get(self.dequeue_url, REMOTE_ADDR='127.0.0.1')
                    if response.status_code == 200:
                        results['worker1'] = response.data.get('id')
                    else:
                        results[
                            'worker1_error'] = f"HTTP {response.status_code}: {response.content.decode('utf-8')[:200]}"
            except Exception as e:
                results['worker1_error'] = f"Exception: {str(e)}"
            finally:
                connection.close()

        def worker_2():
            # Wait for thread 1 to start its save() and grab the row lock
            thread1_locked.wait(timeout=3.0)
            time.sleep(0.2)  # Ensure select_for_update is fully engaged

            try:
                response = client2.get(self.dequeue_url, REMOTE_ADDR='127.0.0.1')
                if response.status_code == 200:
                    results['worker2'] = response.data.get('id')
                else:
                    results['worker2_error'] = f"HTTP {response.status_code}: {response.content.decode('utf-8')[:200]}"
            except Exception as e:
                results['worker2_error'] = f"Exception: {str(e)}"
            finally:
                connection.close()

        t1 = threading.Thread(target=worker_1)
        t2 = threading.Thread(target=worker_2)

        t1.start()
        t2.start()

        t1.join()
        t2.join()

        # Check results
        self.assertIsNotNone(
            results.get('worker1'),
            f"Worker 1 failed! Reason: {results.get('worker1_error')}"
        )
        self.assertIsNotNone(
            results.get('worker2'),
            f"Worker 2 failed! Reason: {results.get('worker2_error')}"
        )

        # Confirm they grabbed different trials
        self.assertEqual(
            results['worker1'],
            str(self.trial_1.id),
            "Worker 1 did not get Trial 1"
        )

        self.assertEqual(
            results['worker2'],
            str(self.trial_2.id),
            "Worker 2 did not skip locked Trial 1 to get Trial 2"
        )

        # Confirm they updated correctly in the database
        self.trial_1.refresh_from_db()
        self.trial_2.refresh_from_db()
        self.assertEqual(self.trial_1.status, "processing")
        self.assertEqual(self.trial_2.status, "processing")