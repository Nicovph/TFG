"""Promote an existing federated user to Django admin privileges.

   The commands could be python manage.py promote_user --user-id <uuid-local>
   or python manage.py promote_user --google-subject <sub-de-google>
"""
import uuid

# BaseCommand is the base class that a personalized command must extends.
# CommandError is used to inform controlled errors of the command.
from django.core.management.base import BaseCommand, CommandError, CommandParser

from backend.accounts.models import CustomUser
from backend.accounts.services import promote_user


class Command(BaseCommand):
    """Promote a local federated user without exposing an HTTP endpoint."""

    # Description that will appear when executing python manage.py help promote_user.
    help = (
        "Promote an existing Google OIDC-backed local user to staff and "
        "superuser status."
    )

    # Defines the accepted command argumnets.
    def add_arguments(self, parser: CommandParser) -> None:
        """Configure command-line arguments for selecting one local user.

        Args:
            parser: The Django command parser to configure.
        """
        # Creates a group of mutually exclusive arguments (it means, only one command can be used at a time).
        selector_group = parser.add_mutually_exclusive_group(required=True)
        selector_group.add_argument(
            "--user-id",
            dest="user_id",
            help="Local UUID of the user to promote.",
        )
        selector_group.add_argument(
            "--google-subject",
            dest="google_subject",
            help="Opaque Google OIDC sub claim of the user to promote.",
        )

    # Method called when the command is executed.
    def handle(self, *_args: object, **options: object) -> None:
        """Promote the selected user to staff and superuser.

        Args:
            *_args: Positional command arguments, they exist
                for the sake of compatibility or by convention
                within the Django framework .
            **options: Parsed command options.

        Raises:
            CommandError: If the selected user does not exist.
        """
        user = self._get_user(
            user_id=options.get("user_id"),
            google_subject=options.get("google_subject"),
        )

        if user.is_active and user.is_staff and user.is_superuser:
            self.stdout.write(
                self.style.WARNING(f"User {user.id} is already promoted.")
            )
            return

        promoted_user = promote_user(user)
        self.stdout.write(
            self.style.SUCCESS(f"Promoted user {promoted_user.id}.")
        )

    def _get_user(
        self,
        *,
        user_id: object,
        google_subject: object,
    ) -> CustomUser:
        """Resolve the user selected by the management command options.

        Args:
            user_id: The optional local UUID selector.
            google_subject: The optional Google subject selector.

        Returns:
            The selected CustomUser instance.

        Raises:
            CommandError: If no matching user exists.
        """
        # If user id is a non-empty string.
        if isinstance(user_id, str) and user_id:
            try:
                parsed_user_id = uuid.UUID(user_id)
            except ValueError as exc:
                raise CommandError("El UUID de usuario no es válido.") from exc

            try:
                return CustomUser.objects.get(id=parsed_user_id)
            except CustomUser.DoesNotExist as exc:
                raise CommandError(
                    "No existe un usuario con ese identificador."
                ) from exc

        try:
            if isinstance(google_subject, str) and google_subject:
                return CustomUser.objects.get(google_subject=google_subject)
        except CustomUser.DoesNotExist as exc:
            raise CommandError("No existe un usuario con ese identificador.") from exc

        raise CommandError("Debe indicar un identificador de usuario válido.")
