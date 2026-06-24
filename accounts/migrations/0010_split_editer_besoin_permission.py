from django.db import migrations

def split_editer_besoin(apps, schema_editor):
    RolePermission = apps.get_model('accounts', 'RolePermission')
    for rp in RolePermission.objects.all():
        perms = rp.permissions or []
        if 'editer_besoin' in perms and 'editer_besoin_agence' not in perms:
            try:
                idx = perms.index('editer_besoin')
                perms.insert(idx + 1, 'editer_besoin_agence')
            except ValueError:
                perms.append('editer_besoin_agence')
            rp.permissions = perms
            rp.save()

def reverse_split_editer_besoin(apps, schema_editor):
    RolePermission = apps.get_model('accounts', 'RolePermission')
    for rp in RolePermission.objects.all():
        perms = rp.permissions or []
        if 'editer_besoin_agence' in perms:
            perms = [p for p in perms if p != 'editer_besoin_agence']
            rp.permissions = perms
            rp.save()

class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0009_add_new_finance_permissions'),
    ]

    operations = [
        migrations.RunPython(split_editer_besoin, reverse_code=reverse_split_editer_besoin),
    ]
