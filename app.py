import streamlit as st
import cv2
import numpy as np
import mediapipe as mp
import requests
import pandas as pd
from io import BytesIO
from datetime import datetime
from PIL import Image

# ---------------------------------------------------------
# CONFIGURACIÓN GENERAL
# ---------------------------------------------------------
st.set_page_config(page_title="Sistema de Asistencia PEMEX", layout="centered")

# ---> ASEGÚRATE DE QUE TU URL DE GOOGLE SHEETS ESTÉ CORRECTA AQUÍ <---
WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbxXl7xolaMAD8WyPCbq6EZSHn61Zs8xe9Atc9kzb1Dds5ceKhl_lq0BPKXnl7ZvJKTa/exec"

USUARIO_AUTORIZADO = "ASIS_PEMEX2026"
PASSWORD_AUTORIZADO = "Personal_PEMEX2026"

# Puntos clave del rostro para la huella biométrica
KEY_LANDMARKS = [
    1, 4, 6, 10, 33, 54, 61, 67, 70, 93, 103, 105, 107, 109, 127, 132, 133,
    145, 148, 152, 159, 162, 168, 172, 176, 197, 234, 263, 284, 291, 297,
    300, 323, 332, 334, 336, 338, 356, 361, 362, 374, 377, 386, 389, 397, 400, 454
]

# Inicialización de estado
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
if "modo_cierre" not in st.session_state:
    st.session_state.modo_cierre = False
if "rostros_db" not in st.session_state:
    st.session_state.rostros_db = []

mp_face_mesh = mp.solutions.face_mesh.FaceMesh(
    static_image_mode=True, # Modo imagen estática para mejor precisión en fotos
    max_num_faces=1,
    refine_landmarks=True,
    min_detection_confidence=0.5
)

# ---------------------------------------------------------
# FUNCIONES BIOMÉTRICAS Y DE CONEXIÓN
# ---------------------------------------------------------
def cargar_rostros():
    try:
        resp = requests.post(WEBHOOK_URL, json={"action": "get_faces"}, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "success":
                st.session_state.rostros_db = data.get("rostros", [])
    except Exception as e:
        st.warning("No se pudo conectar a la nube.")

def analizar_foto(imagen_pil):
    """Procesa la foto tomada, extrae el rostro y verifica si está centrado."""
    img_np = np.array(imagen_pil)
    rgb_img = cv2.cvtColor(img_np, cv2.COLOR_BGR2RGB)
    
    resultados = mp_face_mesh.process(rgb_img)
    if not resultados.multi_face_landmarks:
        return False, None, "No se detectó ningún rostro en la foto."

    lms = resultados.multi_face_landmarks[0].landmark
    
    # Extraer el vector facial
    coords = np.array([[lms[i].x, lms[i].y, lms[i].z] for i in KEY_LANDMARKS])
    nariz = coords[0]
    coords_centradas = coords - nariz
    
    ojo_izq = np.array([lms[33].x, lms[33].y])
    ojo_der = np.array([lms[263].x, lms[263].y])
    d_ojos = np.linalg.norm(ojo_der - ojo_izq)
    
    if d_ojos < 1e-6:
        return False, None, "Rostro no alineado."
        
    vector = (coords_centradas / d_ojos).flatten().tolist()
    return True, vector, "Rostro detectado correctamente."

def identificar_rostro(vector_nuevo):
    """Busca a quién pertenece el vector en la base de datos."""
    if not st.session_state.rostros_db or vector_nuevo is None:
        return None
        
    v_actual = np.array(vector_nuevo)
    mejor_nombre = None
    menor_distancia = 0.38 # Umbral de similitud
    
    for registro in st.session_state.rostros_db:
        v_db = np.array(registro["vector"])
        dist = np.linalg.norm(v_actual - v_db)
        if dist < menor_distancia:
            menor_distancia = dist
            mejor_nombre = registro["nombre"]
            
    return mejor_nombre

# ---------------------------------------------------------
# PANTALLAS DE LA APLICACIÓN
# ---------------------------------------------------------
if not st.session_state.autenticado:
    st.title("🔐 Acceso al Sistema PEMEX")
    with st.form("login"):
        u = st.text_input("Usuario")
        p = st.text_input("Contraseña", type="password")
        if st.form_submit_button("Entrar"):
            if u == USUARIO_AUTORIZADO and p == PASSWORD_AUTORIZADO:
                st.session_state.autenticado = True
                cargar_rostros()
                st.rerun()
            else:
                st.error("Credenciales inválidas.")

elif st.session_state.modo_cierre:
    st.title("📊 Corte del Día")
    st.warning("¿Generar reporte en la nube y cerrar sesión?")
    if st.button("✅ Enviar a Google Drive"):
        with st.spinner("Subiendo reporte..."):
            try:
                r = requests.post(WEBHOOK_URL, json={"action": "generate_report"})
                if r.status_code == 200:
                    res = r.json()
                    st.success(f"Reporte enviado a la nube en la carpeta '{res.get('carpeta')}'.")
                    st.markdown(f"🔗 **[Abrir en Drive]({res.get('url_drive')})**")
                    
                    df = pd.DataFrame(res.get("registros", []))
                    buffer = BytesIO()
                    df.to_excel(buffer, index=False)
                    st.download_button("Descargar .xlsx local", buffer.getvalue(), f"Reporte_{datetime.now().strftime('%d-%m-%Y')}.xlsx")
            except Exception as e:
                st.error(f"Error de red: {e}")
                
    if st.button("🚪 Salir al inicio"):
        st.session_state.autenticado = False
        st.session_state.modo_cierre = False
        st.rerun()

else:
    st.sidebar.title("🏢 Panel de Control")
    opcion = st.sidebar.radio("Menú:", ["⏱️ Asistencia", "👤 Alta de Rostro"])
    if st.sidebar.button("🔄 Refrescar BD"):
        cargar_rostros()
        st.sidebar.success(f"Rostros: {len(st.session_state.rostros_db)}")
    if st.sidebar.button("🚪 Corte Diario"):
        st.session_state.modo_cierre = True
        st.rerun()

    # ------------------------------------------
    # MÓDULO A: REGISTRO DE ASISTENCIA
    # ------------------------------------------
    if opcion == "⏱️ Asistencia":
        st.title("Registro de Asistencia")
        tipo = st.radio("Acción:", ["Entrada", "Salida"], horizontal=True)
        
        # Uso del componente nativo de cámara (Funciona perfecto en móviles)
        foto = st.camera_input("Toma una foto de tu rostro centrado:")
        
        if foto is not None:
            img = Image.open(foto)
            exito, vector, msj = analizar_foto(img)
            
            if not exito:
                st.error(msj)
            else:
                nombre_identificado = identificar_rostro(vector)
                if not nombre_identificado:
                    st.error("❌ Rostro no reconocido en la base de datos.")
                else:
                    st.success(f"✅ Rostro Identificado: **{nombre_identificado}**")
                    if st.button(f"Registrar {tipo} para {nombre_identificado}", use_container_width=True, type="primary"):
                        with st.spinner("Enviando a Google Sheets..."):
                            payload = {"action": "log_attendance", "nombre": nombre_identificado, "tipo": tipo}
                            try:
                                r = requests.post(WEBHOOK_URL, json=payload)
                                if r.status_code == 200:
                                    st.success(f"✅ {tipo} registrada a las {r.json().get('hora')}")
                            except:
                                st.error("Error al registrar en la nube.")

    # ------------------------------------------
    # MÓDULO B: ALTA DE ROSTROS
    # ------------------------------------------
    elif opcion == "👤 Alta de Rostro":
        st.title("Alta Biométrica")
        nombre_nuevo = st.text_input("Nombre Completo:")
        
        # Componente nativo de cámara
        foto_alta = st.camera_input("Toma una foto clara para la base de datos:")
        
        if foto_alta is not None and nombre_nuevo:
            img_alta = Image.open(foto_alta)
            exito, vector, msj = analizar_foto(img_alta)
            
            if not exito:
                st.error(f"❌ {msj} Intenta tomar la foto nuevamente con mejor luz.")
            else:
                st.info("Rostro analizado. Listo para guardar.")
                if st.button("💾 Guardar Huella Facial en la Nube", use_container_width=True, type="primary"):
                    with st.spinner("Guardando en Google Sheets..."):
                        payload = {"action": "register_face", "nombre": nombre_nuevo, "vector": vector}
                        try:
                            r = requests.post(WEBHOOK_URL, json=payload)
                            if r.status_code == 200:
                                st.success(f"✅ ¡Rostro de {nombre_nuevo} guardado exitosamente!")
                                cargar_rostros()
                        except:
                            st.error("Error al guardar en la nube.")
                            
        st.markdown("---")
        st.markdown("### Personal en BD")
        if st.session_state.rostros_db:
            st.write(pd.DataFrame({"Nombre": [r["nombre"] for r in st.session_state.rostros_db]}))
        else:
            st.write("Base de datos vacía.")
