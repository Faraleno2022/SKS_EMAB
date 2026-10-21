import uuid as uuid_mod
from datetime import datetime

import bcrypt
from django import forms
from django.contrib import admin
from django.contrib.auth import get_user_model

from sync.models import (
    Device,
    Product,
    RemoteUser,
    Sale,
    StockMovement,
    Transaction,
)


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("name", "active", "created_at", "last_seen")
    readonly_fields = ("token", "created_at", "last_seen")
    search_fields = ("name",)


ROLE_CHOICES = [
    ("super_admin", "Super administrateur"),
    ("admin", "Administrateur"),
    ("superviseur", "Superviseur"),
    ("caissier", "Caissier"),
]


class RemoteUserAdminForm(forms.ModelForm):
    """Saisie d'un mot de passe en clair, enregistré en bcrypt (comme le poste).

    Permet de créer le premier super administrateur d'une base neuve depuis
    /admin/, sans Shell Render ni hash bcrypt calculé à la main.
    """

    role = forms.ChoiceField(choices=ROLE_CHOICES)
    password = forms.CharField(
        label="Mot de passe", required=False, strip=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Obligatoire à la création ; laisser vide pour conserver le mot de passe actuel.",
    )

    class Meta:
        model = RemoteUser
        fields = ("identifiant", "nom_complet", "matricule", "telephone", "role", "actif", "can_delete")

    def clean_identifiant(self):
        identifiant = self.cleaned_data["identifiant"].strip()
        if RemoteUser.objects.filter(identifiant=identifiant).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(f"L'identifiant « {identifiant} » existe déjà.")
        return identifiant

    def clean(self):
        cleaned = super().clean()
        if not self.instance.pk and not cleaned.get("password"):
            self.add_error("password", "Le mot de passe est obligatoire à la création.")
        return cleaned


@admin.register(RemoteUser)
class RemoteUserAdmin(admin.ModelAdmin):
    form = RemoteUserAdminForm
    list_display = ("identifiant", "nom_complet", "role", "actif", "received_at")
    search_fields = ("identifiant", "nom_complet", "matricule")
    list_filter = ("role", "actif")

    def save_model(self, request, obj, form, change):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not obj.uuid:
            obj.uuid = str(uuid_mod.uuid4())
        if not obj.created_at:
            obj.created_at = now
        obj.updated_at = now
        password = form.cleaned_data.get("password")
        if password:
            obj.password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
            # Un compte Django du même nom (createsuperuser) garderait sinon son
            # ancien mot de passe : s'y connecter ouvrirait une session sans rôle.
            mirror = get_user_model().objects.filter(username=obj.identifiant).first()
            if mirror and mirror.has_usable_password():
                mirror.set_unusable_password()
                mirror.save(update_fields=["password"])
        super().save_model(request, obj, form, change)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("nom", "reference", "prix_unitaire", "quantite_stock", "actif", "received_at")
    search_fields = ("nom", "reference")


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("product_nom", "type", "quantite", "stock_apres", "created_at", "received_at")
    list_filter = ("type",)
    search_fields = ("product_nom",)


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("matricule", "type", "montant", "solde_apres", "agent_nom", "created_at", "deleted")
    list_filter = ("type", "deleted")
    search_fields = ("matricule", "agent_nom")


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ("matricule", "product_nom", "quantite", "montant_total", "agent_nom", "created_at", "deleted")
    list_filter = ("deleted",)
    search_fields = ("matricule", "product_nom", "agent_nom")
