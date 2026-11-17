---
name: logistics-and-operations-kpis
description: Define and structure key performance indicators (KPIs) for logistics processes, including formulas, data sources, targets, and action plans to support data-driven decision-making.
version: 1.0.0
author: SkillsHub MCP
license: MIT
category: Business
tags: [logistics, KPI, operations, metrics, business]
---

# Logistics and Operations KPIs

## Objective
Transform logistics and operations processes into trackable, objective metrics. This skill generates a structured set of key performance indicators (KPIs) that eliminate management by perception and establish a solid foundation for data-driven decision-making.

## When to Use
- When creating a dashboard after documenting a Standard Operating Procedure (SOP).
- When there is uncertainty about whether a process is functioning optimally or poorly.
- To justify proposals for operational improvements to senior management using quantifiable data.
- When you need to standardize how performance is reported to the executive team or management.
- When implementing a new management system (WMS, ERP) and needing to define which metrics will be extracted from it.

## How to Use
1. Provide the context of the logistics process you want to measure (receiving, storage, picking, shipping, transportation, etc.).
2. Define the main objective of the process and the recurring issues you want to monitor.
3. Specify the systems available for data extraction (WMS, ERP, spreadsheets) and the frequency of review.
4. Run the prompt to obtain a set of 5 to 7 KPIs with their formulas, alert thresholds, and action plans.
5. Implement data collection in your systems and monitor the results weekly or monthly.

## Practical Examples

**Input example:**
```text
- Proceso: Recepción de Mercancías
- Objetivo: Recibir la mercancía a tiempo, sin discrepancias y con el stock actualizado
- Problemas: Discrepancias en cantidades, retraso en la puesta a disposición, facturas rechazadas
- Sistemas: WMS + hoja de cálculo de control
- Frecuencia: Revisión semanal
- Reporta a: Supervisor y gerente de operaciones
```

**Example prompt to run:**
```text
Eres un experto en indicadores de desempeño para operaciones logísticas y gestión de almacenes. Tus principios son: (1) medir todo es medir nada: un proceso bien gestionado tiene entre 3 y 7 KPI; (2) cada KPI necesita un objetivo (verde), una banda de alerta (amarillo) y un disparador de acción (rojo); (3) la fuente de datos debe ser fiable y accesible; (4) un conjunto saludable combina KPI de proceso (ejecución) y KPI de resultado (impacto).

Proceso a monitorear: Recepción de Mercancías
Objetivo del proceso: Recibir a tiempo, sin discrepancias y con stock actualizado
Problemas recurrentes: Discrepancias en cantidades, retraso en lanzamiento, facturas rechazadas
Sistemas disponibles: WMS + hoja de cálculo
Frecuencia de gestión: Revisión semanal
Reportar a: Supervisor y gerencia

Entrega:
1. Conjunto de KPI sugeridos (5 a 7) con nombre, fórmula, unidad, fuente y objetivo de referencia.
2. Tabla de seguimiento semanal con KPI, meta, resultado, estado (verde/amarillo/rojo) y responsable.
3. Rangos de rendimiento con valores de corte para verde, amarillo y rojo.
4. Plan de reacción por KPI en rojo: quién lo activa, qué investiga y fecha límite.
5. Mapa de causa y efecto entre KPIs de proceso y de resultado.
```

## Expected Output
The assistant will generate a structured document that includes:
1. **Set of KPIs**: A detailed table with 5 to 7 indicators, their exact calculation formulas, units of measure, and recommended data sources.
2. **Management dashboard**: A ready-to-implement tracking matrix in Excel or Google Sheets, with columns for status indicators (green, yellow, red) and the assigned person in charge.
3. **Performance Ranges**: Clear quantitative thresholds that define when an indicator is on target, on alert, or requires immediate action.
4. **Response Plans**: Steps to follow when a KPI enters the red zone, including the person responsible for investigating the issue and the deadline for submitting a corrective action plan.
5. **Cause-and-effect map**: A logical explanation of how process metrics (e.g., unloading time) directly impact outcome metrics (e.g., total logistics cost).