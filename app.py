import streamlit as st
import cv2
import numpy as np
import mediapipe as mp
import requests
import pandas as pd
from io import BytesIO
from datetime import datetime
from streamlit_webrtc import webrtc_streamer, VideoTransformerBase

# ---------------------------------------------------------
# CONFIGURACIÓN GENERAL Y CREDENCIALES
# ---------------------------------------------------------
st.set_page_config(page_title="Sistema de Asistencia PEMEX", layout="centered")

WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbxXl7xolaMAD8WyPCbq6EZSHn61Zs8xe9Atc9kzb1Dds5ceKhl_lq0BPKXnl7ZvJKTa/exec"
USUARIO_AUTORIZADO = "ASIS_PEMEX2026"
PASSWORD_AUTORIZADO = "Personal_PEMEX2026"

# Puntos clave del rostro para crear la huella geométrica (invariante a escala y posición)
KEY_LANDMARKS = [
    1, 4, 6, 10, 33, 54, 61, 67, 70, 93, 103, 105, 107, 109, 127, 132, 133,
    145, 148, 152, 159, 162, 168, 172, 176, 197, 234, 263, 284, 291, 297,
    300, 323, 332, 334, 336, 338, 356, 361, 362, 374, 377, 386, 389, 397, 400, 454
]

# Inicializar variables de estado de sesión
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
if "modo_cierre" not in st.session_state:
    st.session_state.modo_cierre = False
if "rostros_db" not in st.session_state:
    st.session_state.rostros_db = []

# ---------------------------------------------------------
# FUNCIONES DE CONEXIÓN A LA NUBE Y BIOMETRÍA
# ---------------------------------------------------------
def cargar_rostros_desde_nube():
    """Descarga las huellas faciales guardadas en Google Sheets."""
    try:
        resp = requests.post(WEBHOOK_URL, json={"action": "get_faces"}, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "success":
                st.session_state.rostros_db = data.get("rostros", [])
    except Exception as e:
        st.warning(f"No se pudieron sincronizar los rostros: {e}")

def extraer_vector_facial(landmarks):
    """Genera un vector biométrico normalizado a partir de los puntos de MediaPipe."""
    coords = np.array([[landmarks[i].x, landmarks[i].y, landmarks[i].z] for i in KEY_LANDMARKS])
    # Centrar en la punta de la nariz (índice 0 de nuestra lista = landmark 1)
    nariz = coords[0]
    coords_centradas = coords - nariz

    # Alinear rotación usando la línea entre ambos ojos (landmarks 33 y 263)
    ojo_izq = np.array([landmarks[33].x, landmarks[33].y])
    ojo_der = np.array([landmarks[263].x, landmarks[263].y])
    d_ojos = np.linalg.norm(ojo_der - ojo_izq)
    if d_ojos < 1e-6:
        return None

    # Normalizar por la distancia interocular
    vector_normalizado = (coords_centradas / d_ojos).flatten()
    return vector_normalizado.tolist()

def identificar_persona(vector_actual, base_rostros, umbral=0.38):
    """Compara el rostro en cámara contra la base de datos en la nube."""
    if not base_rostros or vector_actual is None:
        return "Desconocido", 999.0

    v_actual = np.array(vector_actual)
    mejor_nombre = "Desconocido"
    menor_distancia = 999.0

    for registro in base_rostros:
        v_db = np.array(registro["vector"])
        if v_actual.shape == v_db.shape:
            dist = np.linalg.norm(v_actual - v_db)
            if dist < menor_distancia:
                menor_distancia = dist
                mejor_nombre = registro["nombre"]

    if menor_distancia <= umbral:
        return mejor_nombre, menor_distancia
    return "No Registrado", menor_distancia

def calcular_ear(landmarks, w, h):
    """Calcula la relación de aspecto del ojo para detectar parpadeo."""
    p_top = np.array([landmarks[159].x * w, landmarks[159].y * h])
    p_bot = np.array([landmarks[145].x * w, landmarks[145].y * h])
    p_l = np.array([landmarks[33].x * w, landmarks[33].y * h])
    p_r = np.array([landmarks[133].x * w, landmarks[133].y * h])
    return np.linalg.norm(p_top - p_bot) / (np.linalg.norm(p_l - p_r) + 1e-6)

# ---------------------------------------------------------
# PROCESADOR DE VIDEO CON MARCO DE ENFOQUE
# ---------------------------------------------------------
mp_face_mesh = mp.solutions.face_mesh

class BiometricTransformer(VideoTransformerBase):
    def __init__(self):
        self.face_mesh = mp_face_mesh.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.6,
            min_tracking_confidence=0.6
        )
        self.liveness_passed = False
        self.blink_counter = 0
        self.face_in_box = False
        self.current_vector = None
        self.detected_name = "Buscando..."
        self.rostros_conocidos = []

    def transform(self, frame):
        img = frame.to_ndarray(format="bgr24")
        img = cv2.flip(img, 1)  # Efecto espejo para facilitar que la persona se ubique
        h, w, _ = img.shape

        # Definir las coordenadas del Marco Guía de Enfoque en el centro
        box_x1, box_y1 = int(w * 0.25), int(h * 0.12)
        box_x2, box_y2 = int(w * 0.75), int(h * 0.88)

        rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        results = self.face_mesh.process(rgb_img)

        self.face_in_box = False

        if results.multi_face_landmarks:
            for face_landmarks in results.multi_face_landmarks:
                lms = face_landmarks.landmark
                x_min = int(min([lm.x for lm in lms]) * w)
                y_min = int(min([lm.y for lm in lms]) * h)
                x_max = int(max([lm.x for lm in lms]) * w)
                y_max = int(max([lm.y for lm in lms]) * h)

                # Verificar si la cara está dentro de la zona enmarcada
                margen = 25
                if (x_min >= box_x1 - margen and x_max <= box_x2 + margen and
                    y_min >= box_y1 - margen and y_max <= box_y2 + margen):
                    self.face_in_box = True

                    # Extraer huella facial y comparar con la base de datos
                    self.current_vector = extraer_vector_facial(lms)
                    nombre, _ = identificar_persona(self.current_vector, self.rostros_conocidos)
                    self.detected_name = nombre

                    # Detectar parpadeo (anti-fraude)
                    ear = calcular_ear(lms, w, h)
                    if ear < 0.16:
                        self.blink_counter += 1
                    else:
                        if self.blink_counter >= 2:
                            self.liveness_passed = True
                        self.blink_counter = 0

                # Dibujar malla/recuadro facial interno
                color_cara = (0, 255, 0) if (self.face_in_box and self.liveness_passed) else (0, 165, 255)
                cv2.rectangle(img, (x_min, y_min), (x_max, y_max), color_cara, 2)

        # Dibujar el MARCO DE ENFOQUE PRINCIPAL en pantalla
        if not self.face_in_box:
            color_marco = (0, 0, 255)  # Rojo: fuera de zona
            mensaje = "COLOCA TU ROSTRO DENTRO DEL RECUADRO"
        elif not self.liveness_passed:
            color_marco = (0, 255, 255)  # Amarillo: centrado, falta parpadear
            mensaje = f"{self.detected_name} - PARPADEEA PARA VALIDAR"
        else:
            color_marco = (0, 255, 0)  # Verde: listo
            mensaje = f"VALIDADO: {self.detected_name}"

        # Dibujar el recuadro guía y el texto de estado
        cv2.rectangle(img, (box_x1, box_y1), (box_x2, box_y2), color_marco, 3)
        cv2.rectangle(img, (box_x1, box_y1 - 35), (box_x2, box_y1), color_marco, -1)
        cv2.putText(img, mensaje, (box_x1 + 10, box_y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2)

        return img

# ---------------------------------------------------------
# 1. PANTALLA DE LOGIN (ACCESO EXCLUSIVO AUTORIZADO)
# ---------------------------------------------------------
if not st.session_state.autenticado:
    st.title("🔐 Acceso al Sistema de Asistencia")
    st.markdown("Plataforma exclusiva para personal autorizado de control de asistencia.")

    with st.form("login_form"):
        usuario = st.text_input("Usuario:")
        password = st.text_input("Contraseña:", type="password")
        submit = st.form_submit_button("Iniciar Sesión")

        if submit:
            if usuario == USUARIO_AUTORIZADO and password == PASSWORD_AUTORIZADO:
                st.session_state.autenticado = True
                st.session_state.modo_cierre = False
                cargar_rostros_desde_nube()
                st.rerun()
            else:
                st.error("❌ Credenciales incorrectas. Acceso denegado.")

# ---------------------------------------------------------
# 2. PANTALLA DE AUTORIZACIÓN AL CERRAR SESIÓN
# ---------------------------------------------------------
elif st.session_state.modo_cierre:
    st.title("📊 Corte del Día y Cierre de Sesión")
    st.warning("Estás por cerrar la sesión activa. ¿Autorizas generar el reporte en Excel y enviarlo a la nube de la empresa?")

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("✅ Autorizar y Enviar Reporte a la Nube"):
            with st.spinner("Generando reporte del día y subiendo a Google Drive..."):
                try:
                    resp = requests.post(WEBHOOK_URL, json={"action": "generate_report"}, timeout=20)
                    res_data = resp.json()
                    if res_data.get("status") == "success":
                        st.success(f"Reporte guardado en la carpeta '{res_data.get('carpeta')}' de la nube.")
                        st.markdown(f"🔗 **[Abrir Reporte en la Nube de la Empresa]({res_data.get('url_drive')})**")

                        # Generar también el archivo Excel (.xlsx) descargable al instante
                        registros = res_data.get("registros", [])
                        if registros:
                            df = pd.DataFrame(registros)
                        else:
                            df = pd.DataFrame(columns=["Fecha", "Hora", "Nombre Completo", "Tipo de Registro", "Estatus de Jornada"])

                        buffer = BytesIO()
                        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                            df.to_excel(writer, index=False, sheet_name="Asistencia_Dia")

                        fecha_hoy = datetime.now().strftime("%d-%m-%Y")
                        st.download_button(
                            label="📥 Descargar Copia en Excel (.xlsx)",
                            data=buffer.getvalue(),
                            file_name=f"Reporte_Asistencia_{fecha_hoy}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
                    else:
                        st.error(f"Error en el servidor: {res_data.get('message')}")
                except Exception as e:
                    st.error(f"Error de conexión: {e}")

    with col2:
        if st.button("🚪 Salir Definitivamente"):
            st.session_state.autenticado = False
            st.session_state.modo_cierre = False
            st.rerun()

    with col3:
        if st.button("⬅️ Volver al Sistema"):
            st.session_state.modo_cierre = False
            st.rerun()

# ---------------------------------------------------------
# 3. SISTEMA PRINCIPAL (MENÚ DE OPERACIÓN)
# ---------------------------------------------------------
else:
    st.sidebar.title("🏢 Panel de Control")
    st.sidebar.success(f"Operador: {USUARIO_AUTORIZADO}")
    st.sidebar.info("Horario oficial de reporte: 08:00 AM a 07:00 PM")

    opcion = st.sidebar.radio(
        "Selecciona una función:",
        ["⏱️ Registrar Asistencia (Entrada/Salida)", "👤 Dar de Alta Nuevo Rostro"]
    )

    if st.sidebar.button("🔄 Actualizar Base de Rostros"):
        cargar_rostros_desde_nube()
        st.sidebar.success(f"Rostros cargados: {len(st.session_state.rostros_db)}")

    st.sidebar.markdown("---")
    if st.sidebar.button("🚪 Finalizar Sesión / Corte del Día"):
        st.session_state.modo_cierre = True
        st.rerun()

    # =========================================================
    # MÓDULO A: REGISTRAR ASISTENCIA
    # =========================================================
    if opcion == "⏱️ Registrar Asistencia (Entrada/Salida)":
        st.title("⏱️ Kiosco de Registro de Asistencia")
        st.markdown("1. Ubica tu rostro dentro del recuadro central.\n2. **Parpadea** para que el recuadro se ponga en **VERDE**.\n3. Presiona el botón de registro.")

        tipo_evento = st.radio("Tipo de movimiento:", ["Entrada", "Salida"], horizontal=True)

        webrtc_ctx = webrtc_streamer(
            key="kiosco_asistencia",
            video_transformer_factory=BiometricTransformer,
            async_transform=True,
            rtc_configuration={"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]}
        )

        if webrtc_ctx.video_transformer:
            webrtc_ctx.video_transformer.rostros_conocidos = st.session_state.rostros_db

            if st.button("✅ Confirmar y Registrar Asistencia", use_container_width=True):
                vt = webrtc_ctx.video_transformer
                if not vt.face_in_box:
                    st.error("❌ El rostro no está dentro del recuadro guía.")
                elif not vt.liveness_passed:
                    st.error("❌ Debes parpadear frente a la cámara para comprobar que eres una persona real.")
                elif vt.detected_name in ["Buscando...", "Desconocido", "No Registrado"]:
                    st.warning("⚠️ Rostro no identificado en la base de datos. Por favor, regístralo primero en el menú 'Dar de Alta Nuevo Rostro'.")
                else:
                    with st.spinner(f"Registrando {tipo_evento} de {vt.detected_name}..."):
                        payload = {
                            "action": "log_attendance",
                            "nombre": vt.detected_name,
                            "tipo": tipo_evento
                        }
                        try:
                            r = requests.post(WEBHOOK_URL, json=payload, timeout=15)
                            res = r.json()
                            if res.get("status") == "success":
                                st.success(f"✅ ¡Registro exitoso! Empleado: **{vt.detected_name}** | Hora: **{res.get('hora')}** | Pestaña: **{res.get('fecha')}**")
                                vt.liveness_passed = False
                            else:
                                st.error(f"Error al guardar: {res.get('message')}")
                        except Exception as e:
                            st.error(f"Error de red: {e}")

    # =========================================================
    # MÓDULO B: DAR DE ALTA CARAS EN LA BASE DE DATOS
    # =========================================================
    elif opcion == "👤 Dar de Alta Nuevo Rostro":
        st.title("👤 Alta Biométrica de Personal")
        st.markdown("Ingresa el nombre completo del trabajador, pídele que centre su rostro en el recuadro y que **parpadee** antes de guardar.")

        nuevo_nombre = st.text_input("Nombre Completo del Empleado (Ej. Arturo Aguilar):")

        webrtc_reg = webrtc_streamer(
            key="alta_rostro",
            video_transformer_factory=BiometricTransformer,
            async_transform=True,
            rtc_configuration={"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]}
        )

        if webrtc_reg.video_transformer:
            webrtc_reg.video_transformer.rostros_conocidos = st.session_state.rostros_db

            if st.button("💾 Guardar Rostro en la Base de Datos en la Nube", use_container_width=True):
                vt = webrtc_reg.video_transformer
                if not nuevo_nombre.strip():
                    st.error("❌ Debes escribir el nombre completo de la persona.")
                elif not vt.face_in_box or vt.current_vector is None:
                    st.error("❌ La persona debe colocar su rostro dentro del recuadro guía.")
                elif not vt.liveness_passed:
                    st.error("❌ La persona debe parpadear para validar la captura en vivo.")
                else:
                    with st.spinner("Guardando firma facial en la nube..."):
                        payload = {
                            "action": "register_face",
                            "nombre": nuevo_nombre.strip(),
                            "vector": vt.current_vector
                        }
                        try:
                            r = requests.post(WEBHOOK_URL, json=payload, timeout=15)
                            res = r.json()
                            if res.get("status") == "success":
                                st.success(f"✅ El rostro de **{nuevo_nombre}** quedó guardado en la base de datos de la nube.")
                                vt.liveness_passed = False
                                cargar_rostros_desde_nube()
                            else:
                                st.error(f"Error al registrar: {res.get('message')}")
                        except Exception as e:
                            st.error(f"Error de conexión: {e}")

        st.markdown("### 📋 Personal Registrado Actualmente")
        if st.session_state.rostros_db:
            nombres_registrados = [r["nombre"] for r in st.session_state.rostros_db]
            st.write(pd.DataFrame({"Nombre Completo": nombres_registrados}))
        else:
            st.info("Aún no hay rostros registrados en la base de datos.")
