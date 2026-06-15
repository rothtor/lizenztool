import questionary
from rich.console import Console
from rich.table import Table

from .metadata import LicenseInfo

console = Console()

_LICENSE_CHOICES = [
    "CC BY 4.0",
    "CC BY-SA 4.0",
    "CC BY-NC 4.0",
    "CC BY-NC-SA 4.0",
    "CC0 1.0 (Public Domain)",
    "All Rights Reserved",
    "Other (type manually)",
]

_LICENSE_URLS = {
    "CC BY 4.0": "https://creativecommons.org/licenses/by/4.0/",
    "CC BY-SA 4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
    "CC BY-NC 4.0": "https://creativecommons.org/licenses/by-nc/4.0/",
    "CC BY-NC-SA 4.0": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
    "CC0 1.0 (Public Domain)": "https://creativecommons.org/publicdomain/zero/1.0/",
}


def show_metadata_table(info: LicenseInfo) -> None:
    table = Table(title="Found License Metadata", show_header=True, header_style="bold cyan")
    table.add_column("Field", style="dim")
    table.add_column("Value")
    table.add_row("Copyright Holder", info.copyright_holder or "[italic red]not found[/]")
    table.add_row("Year", info.year or "[italic red]not found[/]")
    table.add_row("License Type", info.license_type or "[italic red]not found[/]")
    table.add_row("License URL", info.license_url or "[italic red]not found[/]")
    console.print(table)


def confirm_or_edit(info: LicenseInfo) -> LicenseInfo:
    show_metadata_table(info)

    if not questionary.confirm("Use this metadata as-is?", default=True).ask():
        info = _prompt_fields(info)

    return info


def prompt_manual() -> LicenseInfo:
    console.print("[yellow]No license metadata found. Please enter details manually.[/yellow]\n")
    return _prompt_fields(LicenseInfo())


def _prompt_fields(defaults: LicenseInfo) -> LicenseInfo:
    holder = questionary.text(
        "Copyright holder:",
        default=defaults.copyright_holder,
    ).ask()

    year = questionary.text(
        "Year:",
        default=defaults.year,
    ).ask()

    license_choice = questionary.select(
        "License type:",
        choices=_LICENSE_CHOICES,
        default=defaults.license_type if defaults.license_type in _LICENSE_CHOICES else _LICENSE_CHOICES[0],
    ).ask()

    if license_choice == "Other (type manually)":
        license_type = questionary.text("Enter license name:", default=defaults.license_type).ask()
        license_url = questionary.text("Enter license URL:", default=defaults.license_url).ask()
    else:
        license_type = license_choice
        license_url = _LICENSE_URLS.get(license_choice, defaults.license_url)
        license_url = questionary.text("License URL:", default=license_url).ask()

    return LicenseInfo(
        copyright_holder=holder or "",
        year=year or "",
        license_type=license_type or "",
        license_url=license_url or "",
    )
