"""Admin Django : création d'un utilisateur distant avec un mot de passe en clair."""
import bcrypt
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from sync.models import RemoteUser


# Les pages d'admin chargent leurs CSS via {% static %} : pas de manifeste en test.
@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class RemoteUserAdminTests(TestCase):
    def setUp(self):
        # Base neuve : seul existe le compte Django créé par createsuperuser.
        self.django_admin = get_user_model().objects.create_superuser("LENO", "", "ancien")
        self.client.force_login(self.django_admin)
        self.add_url = reverse("admin:sync_remoteuser_add")

    def form(self, **values):
        data = {"identifiant": "LENO", "nom_complet": "Fara Leno", "matricule": "", "telephone": "",
                "role": "super_admin", "actif": "on", "password": "nouveau"}
        data.update(values)
        return data

    def test_first_super_admin_can_be_created_and_then_manage_users(self):
        self.assertEqual(self.client.post(self.add_url, self.form()).status_code, 302)

        remote = RemoteUser.objects.get(identifiant="LENO")
        self.assertEqual(remote.role, "super_admin")
        self.assertTrue(remote.uuid and remote.created_at and remote.updated_at)
        self.assertTrue(bcrypt.checkpw(b"nouveau", remote.password_hash.encode()))
        # L'ancien mot de passe Django ne doit plus ouvrir de session sans rôle.
        self.django_admin.refresh_from_db()
        self.assertFalse(self.django_admin.has_usable_password())

        self.client.logout()
        self.client.post(reverse("web:login"), {"identifiant": "LENO", "password": "ancien"})
        self.assertNotIn("_auth_user_id", self.client.session)
        self.client.post(reverse("web:login"), {"identifiant": "LENO", "password": "nouveau"})
        self.assertEqual(self.client.session["remote_user"]["role"], "super_admin")
        self.assertEqual(self.client.get(reverse("web:users")).status_code, 200)

    def test_password_is_required_on_creation_and_kept_when_left_blank(self):
        response = self.client.post(self.add_url, self.form(password=""))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(RemoteUser.objects.exists())

        self.client.post(self.add_url, self.form(identifiant="caisse1", role="caissier"))
        remote = RemoteUser.objects.get(identifiant="caisse1")
        old_hash = remote.password_hash
        change_url = reverse("admin:sync_remoteuser_change", args=[remote.pk])
        self.assertEqual(self.client.post(change_url, self.form(identifiant="caisse1", role="caissier",
                                                                nom_complet="Caisse 1", password="")).status_code, 302)
        remote.refresh_from_db()
        self.assertEqual((remote.nom_complet, remote.password_hash), ("Caisse 1", old_hash))

    def test_duplicate_identifiant_is_refused(self):
        self.client.post(self.add_url, self.form(identifiant="caisse1", role="caissier"))
        self.assertEqual(self.client.post(self.add_url, self.form(identifiant="caisse1")).status_code, 200)
        self.assertEqual(RemoteUser.objects.filter(identifiant="caisse1").count(), 1)
