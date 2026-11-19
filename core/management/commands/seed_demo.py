"""Наполнение базы демонстрационными данными.

Запуск: python manage.py seed_demo
Команда ничего не делает, если в базе уже есть люди.
"""
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand

from core.models import Debtor, Event, Person, Purchase


class Command(BaseCommand):
    help = 'Наполняет базу демонстрационными данными (люди, события, покупки, должники).'

    def handle(self, *args, **options):
        if Person.objects.exists():
            self.stdout.write(self.style.WARNING(
                'В базе уже есть люди — демо-данные не добавлены.'
            ))
            return

        ivan = Person.objects.create(full_name='Иванов Иван Иванович', nickname='Иван')
        maria = Person.objects.create(
            full_name='Петрова Мария Сергеевна', nickname='Мария', is_admin=True,
        )
        alex = Person.objects.create(full_name='Сидоров Алексей Павлович', nickname='Лёша')
        olga = Person.objects.create(full_name='Кузнецова Ольга Дмитриевна', nickname='Оля')

        dacha = Event.objects.create(date=date(2026, 11, 7), description='Поездка на дачу')
        party = Event.objects.create(date=date(2026, 11, 8), description='День рождения Марии')

        # Дача: продукты купил Иван, Оля съела половину порции (share = 0.5)
        p1 = Purchase.objects.create(
            event=dacha, person=ivan, description='Продукты для шашлыка',
            amount=Decimal('3250.00'),
        )
        Debtor.objects.create(purchase=p1, person=ivan)
        Debtor.objects.create(purchase=p1, person=maria)
        Debtor.objects.create(purchase=p1, person=alex)
        Debtor.objects.create(purchase=p1, person=olga, share=Decimal('0.5'))

        # Дача: такси оплатила Мария, ездили все по полной
        p2 = Purchase.objects.create(
            event=dacha, person=maria, description='Такси до дачи',
            amount=Decimal('1200.00'),
        )
        for person in (ivan, maria, alex, olga):
            Debtor.objects.create(purchase=p2, person=person)

        # День рождения: торт купила Оля, ели Мария, Лёша и Оля
        p3 = Purchase.objects.create(
            event=party, person=olga, description='Торт и украшения',
            amount=Decimal('1800.00'),
        )
        for person in (maria, alex, olga):
            Debtor.objects.create(purchase=p3, person=person)

        # День рождения: пиццу купил Лёша, сам съел половину порции
        p4 = Purchase.objects.create(
            event=party, person=alex, description='Пицца и напитки',
            amount=Decimal('2450.00'),
        )
        Debtor.objects.create(purchase=p4, person=ivan)
        Debtor.objects.create(purchase=p4, person=maria)
        Debtor.objects.create(purchase=p4, person=alex, share=Decimal('0.5'))
        Debtor.objects.create(purchase=p4, person=olga)

        self.stdout.write(self.style.SUCCESS(
            'Демо-данные добавлены: 4 человека, 2 события, 4 покупки, '
            '15 записей должников.'
        ))
