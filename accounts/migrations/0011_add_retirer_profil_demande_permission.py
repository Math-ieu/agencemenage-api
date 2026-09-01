from django.db import migrations

def add_retirer_profil_permission(apps, schema_editor):
    RolePermission = apps.get_model('accounts', 'RolePermission')
    for rp in RolePermission.objects.all():
        perms = rp.permissions or []
        if 'postuler_demande' in perms and 'retirer_profil_demande' not in perms:
            try:
                idx = perms.index('postuler_demande')
                perms.insert(idx + 1, 'retirer_profil_demande')
            except ValueError:
                perms.append('retirer_profil_demande')
            rp.permissions = perms
            rp.save()
        elif rp.role == 'Admin' and 'retirer_profil_demande' not in perms:
            perms.append('retirer_profil_demande')
            rp.permissions = perms
            rp.save()

def reverse_add_retirer_profil_permission(apps, schema_editor):
    RolePermission = apps.get_model('accounts', 'RolePermission')
    for rp in RolePermission.objects.all():
        perms = rp.permissions or []
        if 'retirer_profil_demande' in perms:
            perms = [p for p in perms if p != 'retirer_profil_demande']
            rp.permissions = perms
            rp.save()

class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0010_split_editer_besoin_permission'),
    ]

    operations = [
        migrations.RunPython(add_retirer_profil_permission, reverse_code=reverse_add_retirer_profil_permission),
    ]
