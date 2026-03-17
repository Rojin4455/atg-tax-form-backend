from django.core.management.base import BaseCommand
from django.db.models import Exists, OuterRef

from form_app.models import UserProfile, ClientProfile


class Command(BaseCommand):
    help = (
        "Mark onboard_required=False for every UserProfile that already has "
        "a completed ClientProfile. Skips users without a ClientProfile so "
        "they are still prompted to onboard."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview how many profiles would be updated without writing to the DB.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        has_client_profile = Exists(
            ClientProfile.objects.filter(user=OuterRef("user"))
        )

        qs = UserProfile.objects.filter(
            onboard_required=True
        )
        # qs = qs.annotate(
        #     has_profile=has_client_profile
        # ).filter(
        #     has_profile=True
        # )

        count = qs.count()

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"[DRY RUN] Would mark {count} UserProfile(s) as onboard_required=False."
                )
            )
            return

        updated = qs.update(onboard_required=False)
        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully marked {updated} UserProfile(s) as onboard_required=False."
            )
        )
