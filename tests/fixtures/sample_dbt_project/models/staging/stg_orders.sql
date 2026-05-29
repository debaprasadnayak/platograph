SELECT
    o.order_id,
    o.customer_id,
    s.status
FROM {{ source('raw', 'orders') }} AS o
JOIN {{ ref('stg_status') }} AS s ON o.status_id = s.id
