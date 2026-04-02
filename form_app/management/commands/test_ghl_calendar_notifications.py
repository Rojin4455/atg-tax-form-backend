import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from accounts.models import GHLAuthCredentials
from accounts.services import GHLCalendarServices


class Command(BaseCommand):
    help = "Test GHL create calendar notifications API."

    def add_arguments(self, parser):
        parser.add_argument(
            "--calendar-id",
            required=True,
            help="GHL calendarId path parameter.",
        )
        parser.add_argument(
            "--user-id",
            type=str,
            help="Optional user_id to select specific GHL credentials.",
        )
        parser.add_argument(
            "--payload-json",
            type=str,
            help="Optional raw JSON array payload string.",
        )
        parser.add_argument(
            "--payload-file",
            type=str,
            help="Optional path to a JSON file containing the payload array.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print payload and target calendar without calling GHL.",
        )

    def _default_payload(self):
        return [
            {
                "receiverType": "contact",
                "channel": "email",
                "notificationType": "booked",
                "isActive": True,
                "subject": "Appointment booked",
                "body": "Your appointment has been booked successfully.",
                "afterTime": [{"timeOffset": 1, "unit": "hours"}],
                "beforeTime": [{"timeOffset": 1, "unit": "hours"}],
            }
        ]

    def _load_payload(self, payload_json: str | None, payload_file: str | None):
        if payload_json and payload_file:
            raise CommandError("Use either --payload-json or --payload-file, not both.")

        if payload_json:
            try:
                payload = json.loads(payload_json)
            except json.JSONDecodeError as e:
                raise CommandError(f"Invalid --payload-json: {e}") from e
        elif payload_file:
            try:
                payload = json.loads(Path(payload_file).read_text(encoding="utf-8"))
            except OSError as e:
                raise CommandError(f"Could not read --payload-file: {e}") from e
            except json.JSONDecodeError as e:
                raise CommandError(f"Invalid JSON in --payload-file: {e}") from e
        else:
            payload = self._default_payload()

        if not isinstance(payload, list):
            raise CommandError("Payload must be a JSON array.")
        return payload

    def handle(self, *args, **options):
        calendar_id = options["calendar_id"]
        user_id = options.get("user_id")
        payload = self._load_payload(options.get("payload_json"), options.get("payload_file"))
        dry_run = options.get("dry_run", False)

        if user_id:
            creds = GHLAuthCredentials.objects.filter(user_id=user_id).first()
            if not creds:
                raise CommandError(f"No GHLAuthCredentials found for user_id={user_id}.")
        else:
            creds = GHLAuthCredentials.objects.first()
            if not creds:
                raise CommandError("No GHLAuthCredentials found in DB.")

        self.stdout.write(self.style.WARNING(f"Using credentials user_id={creds.user_id}"))
        self.stdout.write(f"Target calendar_id={calendar_id}")
        self.stdout.write(f"Payload:\n{json.dumps(payload, indent=2)}")

        if dry_run:
            self.stdout.write(self.style.SUCCESS("Dry run complete. API call skipped."))
            return

        service = GHLCalendarServices(access_token=creds.access_token)
        try:
            response = service.create_notifications(calendar_id=calendar_id, notifications=payload)
        except Exception as e:
            raise CommandError(str(e)) from e

        self.stdout.write(self.style.SUCCESS("GHL notifications API call succeeded."))
        self.stdout.write(json.dumps(response, indent=2, default=str))
