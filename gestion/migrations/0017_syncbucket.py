from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('gestion', '0016_vente_telephone_client_libre_alter_commande_statut'),
    ]

    operations = [
        migrations.CreateModel(
            name='SyncBucket',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(max_length=64)),
                ('data', models.JSONField(blank=True, default=list)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('entreprise', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sync_buckets', to='gestion.entreprise')),
            ],
            options={
                'indexes': [models.Index(fields=['entreprise', 'key'], name='gestion_syn_entrepr_7bb7f3_idx')],
                'unique_together': {('entreprise', 'key')},
            },
        ),
    ]
