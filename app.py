import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
CORS(app)

# Conexión a Supabase (PostgreSQL) o SQLite local por defecto
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL', 'sqlite:///pos_dominicana.db'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)


# ==========================================
# MODELOS DE BASE DE DATOS
# ==========================================
class Ingrediente(db.Model):
  __tablename__ = 'ingredientes'
  id = db.Column(db.Integer, primary_key=True)
  nombre = db.Column(db.String(100), nullable=False)
  unidad_medida = db.Column(
      db.String(20), nullable=False
  )  # Ej: gramos, unidades, litros
  stock_actual = db.Column(db.Float, nullable=False, default=0.0)
  costo_unitario = db.Column(db.Float, nullable=False, default=0.0)


class ProductoMenu(db.Model):
  __tablename__ = 'productos_menu'
  id = db.Column(db.Integer, primary_key=True)
  nombre = db.Column(db.String(100), nullable=False)
  precio_venta = db.Column(db.Float, nullable=False)
  categoria = db.Column(db.String(50))  # Combutibles, Bebidas, Acompañamientos
  receta = db.relationship('RecetaItem', backref='producto', lazy=True)


class RecetaItem(db.Model):
  __tablename__ = 'receta_items'
  id = db.Column(db.Integer, primary_key=True)
  producto_id = db.Column(
      db.Integer, db.ForeignKey('productos_menu.id'), nullable=False
  )
  ingrediente_id = db.Column(
      db.Integer, db.ForeignKey('ingredientes.id'), nullable=False
  )
  cantidad_requerida = db.Column(
      db.Float, nullable=False
  )  # Cantidad que descuenta por cada venta
  ingrediente = db.relationship('Ingrediente')


class Venta(db.Model):
  __tablename__ = 'ventas'
  id = db.Column(db.Integer, primary_key=True)
  subtotal = db.Column(db.Float, nullable=False)
  itbis = db.Column(db.Float, nullable=False)  # 18% DGII
  total = db.Column(db.Float, nullable=False)
  fecha = db.Column(
      db.DateTime, default=db.func.current_timestamp()
  )


# Crear las tablas en Supabase
with app.app_context():
  db.create_all()


# ==========================================
# MÓDULO 1: NÓMINA AVANZADA (TSS + ISR + CÓDIGO DE TRABAJO)
# ==========================================
@app.route('/api/nomina/calcular-avanzado', methods=['POST'])
def calcular_nomina_avanzada():
  data = request.json
  salario_bruto = float(data.get('salario_bruto', 0))

  # 1. Topes de cotización TSS vigentes (Resoluciones TSS)
  tope_sfp = 232230.0  # Tope cotizable Salud
  tope_afp = 464460.0  # Tope cotizable Pensiones

  base_sfs = min(salario_bruto, tope_sfp)
  base_afp = min(salario_bruto, tope_afp)

  # 2. Deducciones al Empleado (TSS: 5.91% total)
  afp_empleado = base_afp * 0.0287  # 2.87%
  sfs_empleado = base_sfs * 0.0304  # 3.04%
  total_tss_empleado = afp_empleado + sfs_empleado

  # 3. Cálculo de Retención de ISR (Escala Progresiva DGII 2026)
  # El ISR se calcula sobre el salario bruto menos la TSS del empleado (neto gravable mensual antes de ISR)
  neto_gravable_mensual = salario_bruto - total_tss_empleado
  anual_gravable = neto_gravable_mensual * 12

  isr_anual = 0
  # Escala anual DGII: Exento hasta 416,220
  if anual_gravable > 416220.0 and anual_gravable <= 624329.0:
    isr_anual = (anual_gravable - 416220.0) * 0.15
  elif anual_gravable > 624329.0 and anual_gravable <= 867123.0:
    isr_anual = 31216.0 + (anual_gravable - 624329.0) * 0.20
  elif anual_gravable > 867123.0:
    isr_anual = 79776.0 + (anual_gravable - 867123.0) * 0.25

  isr_mensual = isr_anual / 12

  total_descuentos_empleado = total_tss_empleado + isr_mensual
  salario_neto = salario_bruto - total_descuentos_empleado

  # 4. Aportes Patronales (TSS + INFOTEP)
  afp_patronal = base_afp * 0.0710  # 7.10%
  sfs_patronal = base_sfs * 0.0709  # 7.09%
  srl_patronal = salario_bruto * 0.0110  # 1.10% Riesgo Laboral (Riesgo Bajo)
  infotep = salario_bruto * 0.0100  # 1.00% INFOTEP
  total_patronal = afp_patronal + sfs_patronal + srl_patronal + infotep

  # 5. Provisiones Obligatorias (Código de Trabajo RD)
  regalia_pascual = salario_bruto * 0.0833  # 8.33% (1/12)
  vacaciones = salario_bruto * 0.0417  # 4.17%
  costo_real_empresa = (
      salario_bruto + total_patronal + regalia_pascual + vacaciones
  )

  return jsonify({
      "salario_bruto": round(salario_bruto, 2),
      "empleado": {
          "afp_2.87%": round(afp_empleado, 2),
          "sfs_3.04%": round(sfs_empleado, 2),
          "isr_mensual": round(isr_mensual, 2),
          "total_descuentos": round(total_descuentos_empleado, 2),
          "salario_neto_a_pagar": round(salario_neto, 2),
      },
      "empleador": {
          "afp_7.10%": round(afp_patronal, 2),
          "sfs_7.09%": round(sfs_patronal, 2),
          "srl_1.10%": round(srl_patronal, 2),
          "infotep_1%": round(infotep, 2),
          "total_aportes_tss_infotep": round(total_patronal, 2),
      },
      "provisiones_laborales": {
          "regalia_pascual": round(regalia_pascual, 2),
          "vacaciones": round(vacaciones, 2),
      },
      "costo_total_empleador": round(costo_real_empresa, 2),
  })


# ==========================================
# MÓDULO 2: POS Y DESCUENTO AUTOMÁTICO DE RECETAS
# ==========================================
@app.route('/api/pos/vender', methods=['POST'])
def registrar_venta_pos():
  data = request.json
  items = data.get('items', [])  # [{"producto_id": 1, "cantidad": 2}]

  subtotal = 0

  # Validar stock de ingredientes mediante recetas antes de procesar
  for item in items:
    prod = ProductoMenu.query.get(item['producto_id'])
    if not prod:
      return (
          jsonify({
              "error": f"El producto ID {item['producto_id']} no existe."
          }),
          404,
      )

    # Verificar si hay suficientes ingredientes en el inventario
    for r in prod.receta:
      necesario = r.cantidad_requerida * item['cantidad']
      if r.ingrediente.stock_actual < necesario:
        return (
            jsonify({
                "error": (
                    f"Stock agotado de ingrediente '{r.ingrediente.nombre}'."
                    f" Necesario: {necesario}, Disponible:"
                    f" {r.ingrediente.stock_actual}"
                )
            }),
            400,
        )

  # Descontar ingredientes y calcular subtotal
  for item in items:
    prod = ProductoMenu.query.get(item['producto_id'])
    subtotal += prod.precio_venta * item['cantidad']
    for r in prod.receta:
      r.ingrediente.stock_actual -= r.cantidad_requerida * item['cantidad']

  # Cálculo del ITBIS (18% DGII)
  itbis = subtotal * 0.18
  total = subtotal + itbis

  nueva_venta = Venta(subtotal=subtotal, itbis=itbis, total=total)
  db.session.add(nueva_venta)
  db.session.commit()

  return jsonify({
      "mensaje": (
          "Venta registrada con éxito, inventario actualizado y ITBIS"
          " provisionado."
      ),
      "id_venta": nueva_venta.id,
      "subtotal": round(subtotal, 2),
      "itbis_18": round(itbis, 2),
      "total_general": round(total, 2),
  })


# ==========================================
# MÓDULO 3: CONTABILIDAD Y REPORTE DGII
# ==========================================
@app.route('/api/contabilidad/it1-resumen', methods=['GET'])
def reporte_it1():
  ventas = Venta.query.all()
  total_gravado = sum(v.subtotal for v in ventas)
  total_itbis_cobrado = sum(v.itbis for v in ventas)

  return jsonify({
      "descripcion": (
          "Resumen preliminar para Formulario IT-1 (Declaración Jurada de"
          " ITBIS)"
      ),
      "monto_operaciones_gravadas": round(total_gravado, 2),
      "itbis_cobrado_en_ventas": round(total_itbis_cobrado, 2),
      "total_facturado": round(total_gravado + total_itbis_cobrado, 2),
  })


if __name__ == '__main__':
  app.run(debug=True, port=5000)
