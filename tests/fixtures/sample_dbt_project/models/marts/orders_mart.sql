SELECT
    o.order_id,
    o.customer_id,
    SUM(i.amount) AS total_amount
FROM {{ ref('stg_orders') }} AS o
JOIN {{ ref('stg_order_items') }} AS i ON o.order_id = i.order_id
GROUP BY 1, 2
