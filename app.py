import streamlit as st
import streamlit.components.v1 as components
import requests
import pandas as pd
import json
from io import BytesIO
from datetime import datetime

# ---------------------------------------------------------
# CONFIGURACIÓN GENERAL Y CREDENCIALES
# ---------------------------------------------------------
st.set_page_config(page_title="Sistema Biométrico PEMEX", layout="centered")

# ---> ASEGÚRATE DE MANTENER TU URL DE GOOGLE SHEETS AQUÍ <---
WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbxXl7xolaMAD8WyPCbq6EZSHn61Zs8xe9Atc9kzb1Dds5ceKhl_lq0BPKXnl7ZvJKTa/exec"
USUARIO_AUTORIZADO = "ASIS_PEMEX2026"
PASSWORD_AUTORIZADO = "Personal_PEMEX2026"

if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
if "modo_cierre" not in st.session_state:
    st.session_state.modo_cierre = False
if "huellas_db" not in st.session_state:
    st.session_state.huellas_db = []

# ---------------------------------------------------------
# SINCRONIZACIÓN CON GOOGLE SHEETS
# ---------------------------------------------------------
def cargar_huellas_desde_nube():
    try:
        resp = requests.post(WEBHOOK_URL, json={"action": "get_fingerprints"}, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "success":
                lista = data.get("huellas") or data.get("rostros") or []
                huellas_limpias = []
                for item in lista:
                    cred = item.get("credencial_id") or item.get("vector")
                    if item.get("nombre") and cred:
                        huellas_limpias.append({
                            "nombre": str(item["nombre"]),
                            "credencial_id": str(cred)
                        })
                st.session_state.huellas_db = huellas_limpias
    except Exception as e:
        st.warning(f"Error al sincronizar con la nube: {e}")

# ---------------------------------------------------------
# COMPONENTE WEBAUTHN: ALTA DE HUELLA
# ---------------------------------------------------------
def renderizar_lector_alta(nombre_empleado):
    nombre_escapado = json.dumps(nombre_empleado.strip())
    url_escapada = json.dumps(WEBHOOK_URL)

    html_code = f"""
    <div style="font-family: sans-serif; text-align: center; padding: 15px; border: 2px dashed #0068c9; border-radius: 12px; background-color: #f8f9fa;">
        <div style="font-size: 48px; margin-bottom: 10px;">👆</div>
        <h3 style="margin: 5px 0; color: #1f2937;">Sensor Biométrico Listo</h3>
        <p style="font-size: 14px; color: #4b5563; margin-bottom: 15px;">
            Empleado a registrar: <b>{nombre_empleado}</b>
        </p>
        <button id="btn_alta" onclick="registrarHuella()" style="
            background-color: #0068c9; color: white; border: none; padding: 14px 24px;
            font-size: 16px; font-weight: bold; border-radius: 8px; cursor: pointer; width: 100%;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
            🔐 Escanear Huella en el Teléfono y Guardar
        </button>
        <div id="status_box" style="margin-top: 15px; font-size: 14px; font-weight: bold;"></div>
    </div>

    <script>
    function bufferToBase64url(buffer) {{
        const bytes = new Uint8Array(buffer);
        let str = "";
        for (let charCode of bytes) str += String.fromCharCode(charCode);
        return btoa(str).replace(/\\+/g, "-").replace(/\\//g, "_").replace(/=+$/, "");
    }}

    async function registrarHuella() {{
        const statusBox = document.getElementById("status_box");
        const btn = document.getElementById("btn_alta");
        const nombre = {nombre_escapado};
        const webhookUrl = {url_escapada};

        try {{
            btn.disabled = true;
            statusBox.style.color = "#d97706";
            statusBox.innerHTML = "⏳ Coloca tu dedo en el lector de huella del teléfono...";

            // Inyectamos la función en la ventana principal para evitar el TypeError de seguridad del iframe
            if (window.parent && !window.parent.obtenerHuellaAlta) {{
                window.parent.obtenerHuellaAlta = async function(nombreEmpleado) {{
                    const challenge = new Uint8Array(32);
                    crypto.getRandomValues(challenge);
                    const userId = new Uint8Array(16);
                    crypto.getRandomValues(userId);

                    const publicKey = {{
                        challenge: challenge,
                        rp: {{ name: "Sistema PEMEX" }},
                        user: {{ id: userId, name: nombreEmpleado, displayName: nombreEmpleado }},
                        pubKeyCredParams: [{{ type: "public-key", alg: -7 }}, {{ type: "public-key", alg: -257 }}],
                        authenticatorSelection: {{ userVerification: "preferred" }},
                        timeout: 60000
                    }};
                    const cred = await navigator.credentials.create({{ publicKey }});
                    return cred.rawId;
                }};
            }}

            // Ejecutamos la función en la ventana principal
            const rawId = await window.parent.obtenerHuellaAlta(nombre);
            const credId = bufferToBase64url(rawId);

            statusBox.style.color = "#2563eb";
            statusBox.innerHTML = "☁️ Huella procesada. Guardando en la nube...";

            const payload = {{ action: "register_fingerprint", nombre: nombre, credencial_id: credId, vector: credId }};
            const response = await fetch(webhookUrl, {{ method: "POST", body: JSON.stringify(payload) }});
            const resData = await response.json();
            
            if (resData.status === "success") {{
                statusBox.style.color = "#16a34a";
                statusBox.innerHTML = "✅ ¡Huella guardada exitosamente!";
            }} else {{
                statusBox.style.color = "#dc2626";
                statusBox.innerHTML = "❌ Error en BD: " + (resData.message || "");
            }}
        }} catch (err) {{
            statusBox.style.color = "#dc2626";
            statusBox.innerHTML = "❌ Lectura cancelada. (" + err.message + ")";
        }} finally {{
            btn.disabled = false;
        }}
    }}
    </script>
    """
    components.html(html_code, height=300)

# ---------------------------------------------------------
# COMPONENTE WEBAUTHN: REGISTRO DE ASISTENCIA
# ---------------------------------------------------------
def renderizar_lector_asistencia(tipo_movimiento, huellas_registradas):
    huellas_json = json.dumps(huellas_registradas)
    tipo_json = json.dumps(tipo_movimiento)
    url_escapada = json.dumps(WEBHOOK_URL)

    html_code = f"""
    <div style="font-family: sans-serif; text-align: center; padding: 20px; border: 2px solid #16a34a; border-radius: 12px; background-color: #f0fdf4;">
        <div style="font-size: 54px; margin-bottom: 10px;">☝️</div>
        <h3 style="margin: 5px 0; color: #166534;">Lector de Huella Activo</h3>
        <p style="font-size: 14px; color: #374151; margin-bottom: 15px;">
            Movimiento seleccionado: <b>{tipo_movimiento}</b>
        </p>
        <button id="btn_asistencia" onclick="verificarHuella()" style="
            background-color: #16a34a; color: white; border: none; padding: 16px 24px;
            font-size: 17px; font-weight: bold; border-radius: 8px; cursor: pointer; width: 100%;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
            🔓 Validar Huella y Registrar {tipo_movimiento}
        </button>
        <div id="status_asistencia" style="margin-top: 15px; font-size: 15px; font-weight: bold;"></div>
    </div>

    <script>
    function bufferToBase64url(buffer) {{
        const bytes = new Uint8Array(buffer);
        let str = "";
        for (let charCode of bytes) str += String.fromCharCode(charCode);
        return btoa(str).replace(/\\+/g, "-").replace(/\\//g, "_").replace(/=+$/, "");
    }}

    async function verificarHuella() {{
        const statusBox = document.getElementById("status_asistencia");
        const btn = document.getElementById("btn_asistencia");
        const baseHuellas = {huellas_json};
        const tipo = {tipo_json};
        const webhookUrl = {url_escapada};

        if (!baseHuellas || baseHuellas.length === 0) {{
            statusBox.style.color = "#dc2626";
            statusBox.innerHTML = "⚠️ No hay huellas registradas en la base de datos.";
            return;
        }}

        try {{
            btn.disabled = true;
            statusBox.style.color = "#d97706";
            statusBox.innerHTML = "⏳ Escaneando huella dactilar...";

            if (window.parent && !window.parent.obtenerHuellaAsistencia) {{
                window.parent.obtenerHuellaAsistencia = async function(huellasData) {{
                    const base64urlToBufferLocal = function(base64url) {{
                        const padding = "=".repeat((4 - (base64url.length % 4)) % 4);
                        const base64 = (base64url + padding).replace(/\\-/g, "+").replace(/_/g, "/");
                        const rawData = atob(base64);
                        const buffer = new Uint8Array(rawData.length);
                        for (let i = 0; i < rawData.length; ++i) buffer[i] = rawData.charCodeAt(i);
                        return buffer;
                    }};

                    const allowCredentials = huellasData.map(item => ({{
                        type: "public-key",
                        id: base64urlToBufferLocal(item.credencial_id)
                    }}));

                    const challenge = new Uint8Array(32);
                    crypto.getRandomValues(challenge);
                    
                    const publicKey = {{
                        challenge: challenge,
                        allowCredentials: allowCredentials,
                        userVerification: "preferred",
                        timeout: 60000
                    }};
                    const assertion = await navigator.credentials.get({{ publicKey }});
                    return assertion.rawId;
                }};
            }}

            const rawId = await window.parent.obtenerHuellaAsistencia(baseHuellas);
            const credIdLeida = bufferToBase64url(rawId);

            const empleadoEncontrado = baseHuellas.find(item => item.credencial_id === credIdLeida);

            if (!empleadoEncontrado) {{
                statusBox.style.color = "#dc2626";
                statusBox.innerHTML = "❌ Huella no reconocida.";
                btn.disabled = false;
                return;
            }}

            statusBox.style.color = "#2563eb";
            statusBox.innerHTML = "☁️ Identificado: <b>" + empleadoEncontrado.nombre + "</b>. Guardando...";

            const payload = {{ action: "log_attendance", nombre: empleadoEncontrado.nombre, tipo: tipo }};
            const response = await fetch(webhookUrl, {{ method: "POST", body: JSON.stringify(payload) }});
            const resData = await response.json();
            
            if (resData.status === "success") {{
                statusBox.style.color = "#15803d";
                statusBox.innerHTML = "✅ ¡" + tipo + " registrada!<br>👤 <b>" + empleadoEncontrado.nombre + "</b><br>🕒 Hora: " + resData.hora;
            }} else {{
                statusBox.style.color = "#dc2626";
                statusBox.innerHTML = "❌ Error al guardar en Google Sheets.";
            }}
        }} catch (err) {{
            statusBox.style.color = "#dc2626";
            statusBox.innerHTML = "❌ Lectura cancelada. (" + err.message + ")";
        }} finally {{
            btn.disabled = false;
        }}
    }}
    </script>
    """
    components.html(html_code, height=330)

# ---------------------------------------------------------
# PANTALLAS DE LA APLICACIÓN
# ---------------------------------------------------------
if not st.session_state.autenticado:
    st.title("🔐 Acceso al Sistema Biométrico")
    st.markdown("Plataforma exclusiva para personal autorizado de control de asistencia.")

    with st.form("login_form"):
        usuario = st.text_input("Usuario:")
        password = st.text_input("Contraseña:", type="password")
        submit = st.form_submit_button("Iniciar Sesión")

        if submit:
            if usuario == USUARIO_AUTORIZADO and password == PASSWORD_AUTORIZADO:
                st.session_state.autenticado = True
                st.session_state.modo_cierre = False
                cargar_huellas_desde_nube()
                st.rerun()
            else:
                st.error("❌ Credenciales incorrectas. Acceso denegado.")

elif st.session_state.modo_cierre:
    st.title("📊 Corte del Día y Cierre de Sesión")
    st.warning("Estás por finalizar la sesión activa. ¿Autorizas generar el reporte en Excel y enviarlo a la nube de la empresa?")

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("✅ Autorizar y Enviar Reporte a la Nube"):
            with st.spinner("Generando reporte del día y subiendo a Google Drive..."):
                try:
                    resp = requests.post(WEBHOOK_URL, json={"action": "generate_report"}, timeout=20)
                    res_data = resp.json()
                    if res_data.get("status") == "success":
                        st.success(f"Reporte guardado en la carpeta '{res_data.get('carpeta')}' de la nube.")
                        st.markdown(f"🔗 **[Abrir Reporte en Google Drive]({res_data.get('url_drive')})**")

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

else:
    st.sidebar.title("🏢 Panel de Control")
    st.sidebar.success(f"Operador: {USUARIO_AUTORIZADO}")
    st.sidebar.info("Horario oficial de reporte: 08:00 AM a 07:00 PM")

    opcion = st.sidebar.radio(
        "Selecciona una función:",
        ["⏱️ Registrar Asistencia (Entrada/Salida)", "👤 Dar de Alta Huella de Personal"]
    )

    if st.sidebar.button("🔄 Sincronizar Base de Huellas"):
        cargar_huellas_desde_nube()
        st.sidebar.success(f"Huellas activas: {len(st.session_state.huellas_db)}")

    st.sidebar.markdown("---")
    if st.sidebar.button("🚪 Finalizar Sesión / Corte del Día"):
        st.session_state.modo_cierre = True
        st.rerun()

    if opcion == "⏱️ Registrar Asistencia (Entrada/Salida)":
        st.title("⏱️ Registro de Asistencia por Huella")
        st.markdown("Selecciona el tipo de movimiento y presiona el botón verde para validar tu huella en el sensor del teléfono.")
        tipo_evento = st.radio("Tipo de movimiento:", ["Entrada", "Salida"], horizontal=True)
        renderizar_lector_asistencia(tipo_evento, st.session_state.huellas_db)

    elif opcion == "👤 Dar de Alta Huella de Personal":
        st.title("👤 Alta de Huella Dactilar")
        st.markdown("1. Escribe el nombre completo del trabajador y presiona **Enter**.\n2. Toca el botón azul para activar el lector de huella del teléfono y vincularlo en la nube.")

        nuevo_nombre = st.text_input("Nombre Completo del Empleado:")

        if nuevo_nombre.strip():
            renderizar_lector_alta(nuevo_nombre)
        else:
            st.info("👆 Escribe el nombre completo arriba para habilitar el sensor de huella.")

        st.markdown("---")
        col_titulo, col_btn = st.columns([3, 1])
        with col_titulo:
            st.markdown("### 📋 Personal Registrado en la Nube")
        with col_btn:
            if st.button("🔄 Actualizar tabla"):
                cargar_huellas_desde_nube()
                st.rerun()

        if st.session_state.huellas_db:
            df_personal = pd.DataFrame([
                {"Nombre Completo": h["nombre"], "ID Biométrico": h["credencial_id"][:15] + "..."}
                for h in st.session_state.huellas_db
            ])
            st.dataframe(df_personal, use_container_width=True)
        else:
            st.info("Aún no hay huellas registradas en la base de datos.")
