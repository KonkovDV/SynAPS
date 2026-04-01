# Logistics Domain Guide

> **Scope**: Warehouse, yard, fleet, and fulfillment scheduling with time-window and capacity constraints.

<details><summary>🇷🇺 Краткое описание</summary>

В логистике work center — это не обязательно станок: им может быть док, машина, маршрутная бригада или сортировочная зона. Setup означает переподготовку маршрута, перестановку груза, смену транспортного плеча или конфигурации склада. Каноническая модель отлично подходит для fulfillment и dispatch-операций.
</details>

---

## 1. Domain Frame

Jobs are shipments, picking waves, route legs, inbound receiving tasks, or cross-dock flows. Work centers include docks, forklifts, vehicle pools, sorting lanes, picking zones, and delivery routes.

## 2. SDST Mapping

| Canonical setup concept | Logistics realization |
|-------------------------|-----------------------|
| State-to-state change | Route family, cargo profile, or zone switch |
| Setup time | Vehicle loading pattern reset, route resequencing, dock reconfiguration |
| Material loss | Missed slot cost, spoilage, repacking loss, deadhead time |
| Energy penalty | Fuel burn, battery use, refrigeration overhead |

## 3. State Dictionary

| State | Meaning |
|-------|---------|
| `idle` | Asset or zone is ready for work |
| `processing` | Picking, loading, transporting, or sorting is active |
| `setup` | Vehicle, dock, or route reconfiguration is active |
| `blocked` | Waiting for inventory, gate access, customs, or arrival |
| `maintenance` | Vehicle or material-handling equipment service |

## 4. Setup Matrix Semantics

The setup matrix usually depends on:

- cargo type and handling mode
- destination cluster or route family
- temperature-control requirement
- vehicle type or trailer compatibility
- wave cut-off schedule and promised delivery window

## 5. Auxiliary Resources

- forklift or AGV pools
- drivers and shift-qualified crews
- dock doors and yard spots
- reefer capacity
- customs or documentation staff

## 6. KPI Palette

- on-time shipment rate
- dock utilization
- deadhead distance or empty miles
- pick productivity
- vehicle fill rate
- late-window penalty cost

## 7. Compliance and Regulatory Context

Common governance surfaces:

- transport safety and driver-hour rules
- cold-chain compliance
- customs and hazardous-material controls where applicable
- customer SLA commitments

## 8. Example Parametrization

Suggested `domain_attributes` fields:

- `route_cluster`
- `vehicle_type`
- `temperature_band`
- `delivery_window`
- `hazmat_class`
- `dock_zone`
