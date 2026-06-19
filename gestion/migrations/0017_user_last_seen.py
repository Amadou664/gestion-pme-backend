# Generated manually for admin activity tracking.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('gestion', '0016_vente_telephone_client_libre_alter_commande_statut'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='last_seen',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
