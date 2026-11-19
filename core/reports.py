"""Итоговый отчёт о должниках в рамках события.

Матрица долгов строится ОДНИМ SQL-запросом к SQLite (см. MATRIX_SQL):

* в строках и столбцах — участники события. Список участников ограничен
  связью debtors -> purchases -> events (кто потреблял) плюс покупатели,
  связанные с событием через purchases -> events (кто платил);
* на главной диагонали — нули: человек не может быть должен сам себе;
* ячейка (строка A, столбец Б) — сколько A должен Б по итогам события;
  взаимные долги каждой пары участников схлопнуты (нетто-расчёт);
* значения ниже главной диагонали зеркальны значениям выше диагонали
  с обратным знаком, поэтому всю картину долгов можно читать и по одному
  верхнему треугольнику матрицы.

Долг по отдельной покупке:

    доля_должника = share / SUM(share всех должников покупки)
    долг_должника_покупателю = доля_должника * amount покупки

Покупатель, не потреблявший покупку (его нет в debtors), только получает
деньги; покупатель, потребивший свою долю, сам себе не должен — такие
«долги самому себе» отсекаются условием person <> buyer.

Нормализация коэффициентов (split_purchase): перед расчётом доли участников
нормализуются — делятся на сумму коэффициентов должников покупки, поэтому
сумма долей в рамках одной покупки всегда равна 1. Деньги распределяются
пропорционально нормализованным долям с округлением до копеек; разница
округления добавляется к наибольшей доле, чтобы итог совпал с суммой покупки.
"""
from decimal import ROUND_HALF_UP, Decimal

from django.db import connection

MATRIX_SQL = """
WITH ev AS (
    -- покупки выбранного события
    SELECT p.id,
           p.person_id AS buyer_id,
           p.amount
    FROM purchases p
    WHERE p.event_id = %s
),
parts AS (
    -- должники этих покупок и суммарный коэффициент каждой покупки
    SELECT d.purchase_id,
           d.person_id,
           d.share,
           SUM(d.share) OVER (PARTITION BY d.purchase_id) AS total_share
    FROM debtors d
    WHERE d.purchase_id IN (SELECT id FROM ev)
),
direct AS (
    -- «сырые» направленные долги: сколько from_id должен to_id
    -- по всем покупкам события
    SELECT parts.person_id AS from_id,
           ev.buyer_id     AS to_id,
           SUM(parts.share * ev.amount / parts.total_share) AS value
    FROM parts
    JOIN ev ON ev.id = parts.purchase_id
    WHERE parts.person_id <> ev.buyer_id
    GROUP BY parts.person_id, ev.buyer_id
),
participants AS (
    -- участники события: потребители (через debtors) и плательщики
    -- (через purchases), упорядоченные по алфавиту
    SELECT pp.id,
           pp.full_name,
           pp.nickname,
           ROW_NUMBER() OVER (ORDER BY pp.full_name COLLATE NOCASE, pp.id) AS pos
    FROM people pp
    WHERE pp.id IN (
        SELECT buyer_id FROM ev
        UNION
        SELECT person_id FROM parts
    )
)
SELECT a.id              AS row_id,
       a.full_name       AS row_name,
       a.nickname        AS row_nickname,
       a.pos             AS row_pos,
       b.id              AS col_id,
       b.full_name       AS col_name,
       b.nickname        AS col_nickname,
       b.pos             AS col_pos,
       ROUND(COALESCE(d1.value, 0) - COALESCE(d2.value, 0), 2) AS debt
FROM participants a
CROSS JOIN participants b
LEFT JOIN direct d1 ON d1.from_id = a.id AND d1.to_id = b.id
LEFT JOIN direct d2 ON d2.from_id = b.id AND d2.to_id = a.id
ORDER BY a.pos, b.pos
"""


def split_purchase(purchase):
    """Нормализованное разделение суммы покупки между её должниками.

    Коэффициенты участия нормализуются: доля каждого участника

        share_norm = share / SUM(share всех должников покупки)

    поэтому сумма нормализованных долей в рамках одной покупки равна 1
    (например, доли 1 + 1 + 1 + 0,5 превращаются в 0,2857 + 0,2857 +
    0,2857 + 0,1429). Деньги распределяются пропорционально нормализованным
    долям: money = amount * share_norm, с округлением до копеек; разница
    округления добавляется к наибольшей доле, чтобы сумма всех долей
    совпала с суммой покупки.

    Возвращает список словарей {'person', 'share', 'money'} в алфавитном
    порядке людей; для покупки без должников — пустой список.
    """
    debtors = list(
        purchase.debtors.select_related('person')
        .order_by('person__full_name', 'person_id')
    )
    if not debtors:
        return []

    total_share = sum((d.share for d in debtors), Decimal('0'))
    rows = [
        {
            'person': d.person,
            'share': d.share / total_share,
            'money': (purchase.amount * d.share / total_share).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP,
            ),
        }
        for d in debtors
    ]

    # Корректировка округления до копеек: разница между суммой покупки и
    # суммой округлённых долей добавляется к наибольшей доле.
    diff = (purchase.amount - sum((r['money'] for r in rows), Decimal('0'))).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP,
    )
    if diff != Decimal('0'):
        biggest = max(rows, key=lambda r: r['money'])
        biggest['money'] = (biggest['money'] + diff).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP,
        )
    return rows


def build_event_report(event):
    """Возвращает данные отчёта по событию.

    Состав результата:
    * participants — список участников в порядке позиций матрицы;
    * matrix       — матрица долгов n x n (нули на главной диагонали);
    * rows         — строки матрицы для шаблонов/экспорта;
    * totals       — нетто-баланс каждого участника (сумма по строке):
                     положительное значение — должен в целом, отрицательное —
                     ему должны в целом.
    """
    with connection.cursor() as cursor:
        cursor.execute(MATRIX_SQL, [event.pk])
        rows = cursor.fetchall()

    people_by_pos = {}
    for row in rows:
        row_id, row_name, row_nick, row_pos = row[0], row[1], row[2], row[3]
        people_by_pos.setdefault(
            row_pos, {'id': row_id, 'full_name': row_name, 'nickname': row_nick},
        )
    participants = [
        {**people_by_pos[pos], 'pos': pos} for pos in sorted(people_by_pos)
    ]

    n = len(participants)
    matrix = [[0.0] * n for _ in range(n)]
    for row in rows:
        row_pos, col_pos, debt = row[3], row[7], row[8]
        value = round(float(debt), 2)
        matrix[row_pos - 1][col_pos - 1] = 0.0 if value == 0 else value

    totals = [round(sum(row), 2) for row in matrix]
    return {
        'event': event,
        'participants': participants,
        'matrix': matrix,
        'rows': [
            {'person': participants[i], 'values': matrix[i], 'total': totals[i]}
            for i in range(n)
        ],
        'totals': totals,
        'size': n,
    }
