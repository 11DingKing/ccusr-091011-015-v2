"""
释放已过期预约占用的容量

可由 cron 定期调用：python manage.py release_expired_reservations
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.warehouse.models import ZoneReservation
from apps.warehouse.services import _lock_zone_occupancy, release_expired_reservations


class Command(BaseCommand):
    help = '释放已过期预约占用的保管区容量'

    def handle(self, *args, **options):
        zone_ids = (
            ZoneReservation.objects.filter(status='active')
            .values_list('zone_id', flat=True)
            .distinct()
        )
        total = 0
        for zone_id in zone_ids:
            with transaction.atomic():
                _lock_zone_occupancy(zone_id)
                total += release_expired_reservations(zone=zone_id)
        self.stdout.write(self.style.SUCCESS(f'已释放 {total} 条过期预约的容量'))
