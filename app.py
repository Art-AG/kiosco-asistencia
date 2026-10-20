import streamlit as st
import cv2
import numpy as np
import mediapipe as mp
import requests
from streamlit_webrtc import webrtc_streamer, VideoTransformerBase

st.set_page_config(page_title="Kiosco de Asistencia", layout="centered")

# Inicializar MediaPipe Face Mesh
mp_face_mesh = mp.solutions.face_mesh

def distance(p1, p2):
    """Calcula la distancia euclidiana entre dos puntos."""
    return np.linalg.norm(np.array(p1) - np.array(p2))

class FaceMeshTransformer(VideoTransformerBase):
    def __init__(self):
        self.face_mesh = mp_face_mesh.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )
        self.liveness_passed = False
        self.blink_counter = 0

    def transform(self, frame):
        img = frame.to_ndarray(format="bgr24")
        img_h, img_w, _ = img.shape
        
        rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        results = self.face_mesh.process(rgb_img)

        if results.multi_face_landmarks:
            for face_landmarks in results.multi_face_landmarks:
                p_top = (face_landmarks.landmark[159].x * img_w, face_landmarks.landmark[159].y * img_h)
                p_bot = (face_landmarks.landmark[145].x * img_w, face_landmarks.landmark[145].y * img_h)
                p_l = (face_landmarks.landmark[33].x * img_w, face_landmarks.landmark[33].y * img_h)
                p_r = (face_landmarks.landmark[133].x * img_w, face_landmarks.landmark[133].y * img_h)
                
                ear = distance(p_top, p_bot) / distance(p_l, p_r)
                
                if ear < 0.15:
                    self.blink_counter += 1
                else:
                    if self.blink_counter >= 2:
                        self.liveness_passed = True
                    self.blink_counter = 0
                    
                x_min = int(min([lm.x for lm in face_landmarks.landmark]) * img_w)
                y_min = int(min([lm.y for lm in face_landmarks.landmark]) * img_h)
                x_max = int(max([lm.x for lm in face_landmarks.landmark]) * img_w)
                y_max = int(max([lm.y for lm in face_landmarks.landmark]) * img_h)
                
                color = (0, 255, 0) if self.liveness_passed else (0, 0, 255)
                cv2.rectangle(img, (x_min, y_min), (x_max, y_max), color, 2)
                status = "Persona Real Validada" if self.liveness_passed else "Esperando parpadeo..."
                cv2.putText(img, status, (x_min, y_min - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        
        return img

# --- INTERFAZ PRINCIPAL ---
st.title("⏱️ Kiosco de Asistencia")
st.markdown("Selecciona tu nombre, colócate frente a la cámara y **parpadea**.")

empleado = st.selectbox("Selecciona tu nombre:", ["Arturo Aguilar", "Wendy Padilla", "Ángel Perales", "Gabriel Cárdenas"])
tipo_registro = st.radio("¿Qué vas a registrar?", ["Entrada", "Salida"])

webrtc_ctx = webrtc_streamer(
    key="kiosco",
    video_transformer_factory=FaceMeshTransformer,
    async_transform=True,
    rtc_configuration={"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]}
)

if webrtc_ctx.video_transformer:
    if st.button("Registrar Asistencia"):
        if webrtc_ctx.video_transformer.liveness_passed:
            
            # ---> PEGA TU URL EXACTAMENTE ABAJO DE ESTA LÍNEA <---
            webhook_url = "https://script.google.com/macros/s/AKfycbxXl7xolaMAD8WyPCbq6EZSHn61Zs8xe9Atc9kzb1Dds5ceKhl_lq0BPKXnl7ZvJKTa/exec"
            
            datos = {"nombre": empleado, "tipo": tipo_registro}
            
            try:
                respuesta = requests.post(webhook_url, json=datos)
                if respuesta.status_code == 200:
                    st.success(f"✅ Asistencia registrada correctamente para {empleado}.")
                    webrtc_ctx.video_transformer.liveness_passed = False 
                else:
                    st.error("Hubo un error al guardar en la base de datos.")
            except Exception as e:
                st.error(f"Error de conexión: {e}")
        else:
            st.error("❌ Por favor, parpadea para verificar que eres una persona real.")
