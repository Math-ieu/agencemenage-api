from django.db import migrations

def update_role_permissions(apps, schema_editor):
    RolePermission = apps.get_model('accounts', 'RolePermission')
    for rp in RolePermission.objects.all():
        perms = rp.permissions or []
        if "valider_demandes" in perms:
            # remove valider_demandes
            perms = [p for p in perms if p != "valider_demandes"]
            # add traiter_demandes_affectees and creer_valider_demande
            if "traiter_demandes_affectees" not in perms:
                perms.append("traiter_demandes_affectees")
            if "creer_valider_demande" not in perms:
                perms.append("creer_valider_demande")
            rp.permissions = perms
            rp.save()

def reverse_role_permissions(apps, schema_editor):
    RolePermission = apps.get_model('accounts', 'RolePermission')
    for rp in RolePermission.objects.all():
        perms = rp.permissions or []
        if "traiter_demandes_affectees" in perms or "creer_valider_demande" in perms:
            perms = [p for p in perms if p not in ["traiter_demandes_affectees", "creer_valider_demande"]]
            if "valider_demandes" not in perms:
                perms.append("valider_demandes")
            rp.permissions = perms
            rp.save()

class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0007_user_username_passwordresetcode'),
    ]

    operations = [
        migrations.RunPython(update_role_permissions, reverse_code=reverse_role_permissions),
    ]
