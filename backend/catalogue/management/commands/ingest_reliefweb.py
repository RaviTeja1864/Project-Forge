from django.core.management.base import BaseCommand, CommandError

from backend.catalogue.services.reliefweb import (
    MAX_BATCH_SIZE,
    SourceIngestionError,
    ingest_reliefweb_reports,
)


class Command(BaseCommand):
    help = "Ingest published reports from the configured ReliefWeb reports API."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=20,
            help=f"Maximum reports to request (1-{MAX_BATCH_SIZE}; default 20).",
        )

    def handle(self, *args, **options):
        try:
            result = ingest_reliefweb_reports(limit=options["limit"])
        except SourceIngestionError as error:
            raise CommandError(str(error)) from error

        self.stdout.write(
            self.style.SUCCESS(
                f"Received {result.received}; created {result.created}; "
                f"updated {result.updated}; skipped {result.skipped}."
            )
        )
        for reason in result.skip_reasons:
            self.stderr.write(self.style.WARNING(f"Skipped source record: {reason}."))
