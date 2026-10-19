"""Point d'entrée — Gestionnaire Dépôt / Retrait."""
from __future__ import annotations

import os
import sys
import threading
import traceback

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from app.config import APP_NAME, APP_VERSION, BASE_DIR, ICON_PATH, ORG_NAME, ensure_directories
from app.db.database import init_database
from app.services import backup_service, user_service
from app.ui.login_window import LoginWindow
from app.ui.main_window import MainWindow
from app.ui.style import QSS


def _apply_pending_update() -> bool:
    """Si une mise à jour est téléchargée et en attente, l'installe puis relance.

    Retourne True si une mise à jour se lance (il faut alors quitter tout de
    suite pour libérer l'exécutable). Les données ne sont jamais touchées.
    """
    if not getattr(sys, "frozen", False):
        return False  # uniquement en .exe (pas en développement)
    flag = BASE_DIR / "update_pending.flag"
    if not flag.exists():
        return False
    try:
        installer = flag.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    if not installer or not os.path.exists(installer):
        try:
            flag.unlink()
        except OSError:
            pass
        return False

    exe = sys.executable
    exe_name = os.path.basename(exe)
    bat = BASE_DIR / "_apply_update.bat"
    try:
        bat.write_text(
            "@echo off\r\n"
            "ping 127.0.0.1 -n 3 >nul\r\n"  # ~2 s : laisser l'app se fermer
            f'taskkill /IM "{exe_name}" /F >nul 2>&1\r\n'
            "ping 127.0.0.1 -n 2 >nul\r\n"
            f'"{installer}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART\r\n'
            "if errorlevel 1 exit /b 1\r\n"
            f'del "{installer}" >nul 2>&1\r\n'
            f'del "{flag}" >nul 2>&1\r\n'
            f'start "" "{exe}"\r\n'
            'del "%~f0" >nul 2>&1\r\n',
            encoding="utf-8",
        )
    except OSError:
        return False

    import subprocess
    DETACHED_PROCESS = 0x00000008
    CREATE_NO_WINDOW = 0x08000000
    try:
        subprocess.Popen(
            ["cmd", "/c", str(bat)],
            creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
            close_fds=True,
        )
    except Exception:
        return False
    return True


def _check_update_in_background() -> None:
    """Télécharge une éventuelle nouvelle version pendant que l'app tourne.

    Elle s'installera toute seule au prochain lancement de l'app.
    """
    def worker() -> None:
        try:
            from app.updater import check_and_prepare_update
            ready = check_and_prepare_update(APP_VERSION, BASE_DIR)
            if ready:
                print(f"[MAJ] Version {ready} téléchargée — elle s'installera "
                      f"au prochain démarrage (vos données sont conservées).")
        except Exception:
            pass
    threading.Thread(target=worker, daemon=True).start()


def main() -> int:
    ensure_directories()

    # Mise à jour en attente ? On l'applique avant d'ouvrir la fenêtre :
    # l'app redémarre toute seule en version à jour.
    if _apply_pending_update():
        return 0

    # Vérifie en arrière-plan si une nouvelle version est publiée sur GitHub.
    _check_update_in_background()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))
    app.setStyleSheet(QSS)

    try:
        init_database()
        user_service.retire_legacy_default_admin()
    except Exception as e:
        traceback.print_exc()
        QMessageBox.critical(None, "Erreur d'initialisation", str(e))
        return 1
    # Plus de compte créé d'office : sur un poste neuf, les comptes viennent du
    # serveur par la synchronisation (sync_config.json ou Administration → Synchronisation).
    no_account_yet = not user_service.has_active_user()

    # Fichier `sync_config.json` déposé à côté de l'application ? On l'applique
    # (URL serveur, jeton, nom du poste) puis on le renomme. Une erreur de
    # format est signalée mais ne bloque pas le démarrage.
    try:
        from app.services import sync_config_file
        applied = sync_config_file.apply_sync_config_file_if_present()
        if applied is not None:
            print(f"Configuration de synchronisation importée depuis {applied}")
    except Exception as e:
        traceback.print_exc()
        QMessageBox.warning(
            None, "Configuration de synchronisation",
            "Le fichier sync_config.json n'a pas pu être appliqué :\n"
            f"{e}\n\n"
            "Corrigez-le ou configurez la synchronisation dans "
            "Administration → Synchronisation.",
        )

    if no_account_yet:
        QMessageBox.information(
            None, "Aucun compte",
            "Aucun compte n'existe encore sur ce poste.\n\n"
            "Les comptes sont récupérés depuis le serveur par la synchronisation : "
            "déposez le fichier sync_config.json à côté de l'application, "
            "puis relancez-la (le poste doit être connecté à Internet).",
        )

    # Sauvegarde planifiée : exécutée au démarrage si la périodicité est échue.
    try:
        created = backup_service.run_auto_backup_if_due()
        if created is not None:
            print(f"Sauvegarde planifiée créée : {created.name}")
    except Exception:
        traceback.print_exc()  # une sauvegarde ratée ne doit pas bloquer l'appli

    while True:
        login = LoginWindow()
        if login.exec() != QDialog.Accepted or login.user is None:
            return 0
        win = MainWindow(login.user)
        win.show()
        app.exec()
        # à la fermeture, on retourne au login (déconnexion)


if __name__ == "__main__":
    sys.exit(main())
