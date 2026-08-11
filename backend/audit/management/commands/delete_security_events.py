"""Delete old security events after showing a count and confirming 
with python manage.py delete_security_events --older-than-days <days>."""

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from backend.audit.models import SecurityEvent


class Command(BaseCommand):
    """Delete security events through an explicit manual maintenance flow."""

    help = (
        "Elimina eventos de seguridad con la antigüedad indicada, previa "
        "confirmación manual."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        """Require the minimum age of events selected for deletion.

        Args:
            parser: Django command parser to configure.
        """
        parser.add_argument(
            "--older-than-days",
            type=int,
            required=True,
            help="Antigüedad mínima de los eventos, expresada en días.",
        )

    def handle(self, *_args: object, **_options: object) -> None:
        """Count, confirm, and delete the current audit event rows.

        Args:
            *_args: Positional command arguments retained for Django
                compatibility.
            **_options: Standard options and the required retention age.

        Raises:
            CommandError: If the supplied age is not a positive integer.
        """
        retention_days = _options.get("older_than_days")
        if (
            not isinstance(retention_days, int)
            or isinstance(retention_days, bool)
            or retention_days < 1
        ):
            raise CommandError(
                "La antigüedad debe ser un número entero mayor que cero."
            )

        # The fixed cutoff prevents events created during confirmation from
        # being included in this destructive maintenance operation.
        cutoff = timezone.now() - timedelta(days=retention_days)
        candidate_count = SecurityEvent.objects.filter(
            occurred_at__lte=cutoff,
        ).count()
        self.stdout.write(
            # Precision down to the second.
            f"Fecha límite incluida: {cutoff.isoformat(timespec='seconds')}."
        )
        self.stdout.write(
            f"Eventos de seguridad que se eliminarán: {candidate_count}."
        )

        if candidate_count == 0:
            return

        confirmation = input(
            'Escribe "ELIMINAR" para confirmar la eliminación permanente: '
        )
        if confirmation != "ELIMINAR":
            self.stdout.write(
                self.style.WARNING(
                    "Operación cancelada; no se eliminó ningún evento."
                )
            )
            return

        deleted_count = SecurityEvent.objects.delete_through(cutoff=cutoff)
        self.stdout.write(
            self.style.SUCCESS(
                f"Eventos de seguridad eliminados: {deleted_count}."
            )
        )
