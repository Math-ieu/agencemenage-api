from django.db import migrations

def add_new_finance_permissions(apps, schema_editor):
    RolePermission = apps.get_model('accounts', 'RolePermission')
    
    new_perms_all = [
        "consulter_dus_agences_profils",
        "validation_paiements_dus",
        "consulter_suivi_commerciaux",
        "filtrer_suivi_commerciaux",
        "consulter_tresorerie",
        "creer_mouvements_tresorerie",
        "filtrer_tresorerie"
    ]
    
    mapping = {
        "Admin": new_perms_all,
        "Moderateur": new_perms_all,
        "Responsable commercial": new_perms_all,
        "Responsable des Opérations": [
            "consulter_dus_agences_profils",
            "consulter_suivi_commerciaux",
            "filtrer_suivi_commerciaux",
            "consulter_tresorerie",
            "creer_mouvements_tresorerie",
            "filtrer_tresorerie",
            "validation_paiements_dus"
        ],
        "commercial": [
            "creer_mouvements_tresorerie"
        ],
    }

    for role_name, perms_to_add in mapping.items():
        rp = RolePermission.objects.filter(role=role_name).first()
        if rp:
            perms = rp.permissions or []
            updated = False
            for p in perms_to_add:
                if p not in perms:
                    perms.append(p)
                    updated = True
            if updated:
                rp.permissions = perms
                rp.save()

def remove_new_finance_permissions(apps, schema_editor):
    RolePermission = apps.get_model('accounts', 'RolePermission')
    new_perms_all = [
        "consulter_dus_agences_profils",
        "validation_paiements_dus",
        "consulter_suivi_commerciaux",
        "filtrer_suivi_commerciaux",
        "consulter_tresorerie",
        "creer_mouvements_tresorerie",
        "filtrer_tresorerie"
    ]
    for rp in RolePermission.objects.all():
        perms = rp.permissions or []
        filtered_perms = [p for p in perms if p not in new_perms_all]
        if len(filtered_perms) != len(perms):
            rp.permissions = filtered_perms
            rp.save()

class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0008_update_permissions_logic'),
    ]

    operations = [
        migrations.RunPython(add_new_finance_permissions, reverse_code=remove_new_finance_permissions),
    ]
