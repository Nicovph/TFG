#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run administrative tasks.

    Raises:
        ImportError: If Django is not installed or available to Python.
    """
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Traductor_TEA.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "No se pudo importar Django. Comprueba que esté instalado y "
            "disponible en la variable de entorno PYTHONPATH. ¿Has olvidado "
            "activar el entorno virtual?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
