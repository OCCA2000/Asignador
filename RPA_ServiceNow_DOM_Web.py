#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Controlador Web para Automatización RPA ServiceNow DOM
Permite ejecutar y parametrizar todas las funciones del menú de RPA_ServiceNow_DOM_E2E
de forma desatendida y controlada directamente desde la interfaz web.
"""

import os
import sys
import time
import argparse
from datetime import datetime, timedelta

# Importar lógica base de RPA_ServiceNow_DOM_E2E
import RPA_ServiceNow_DOM_E2E as rpa
from Programas.PipelineUtils import (
    ExecutionLogger,
    clean_all_input_csv_files,
    check_file_freshness,
    delete_unprocessed_input_files,
)


def web_run_downloads(download_incidents=True, download_requirements=True, min_mtime=None):
    """
    Descarga desatendida desde ServiceNow compatible con la web (sin llamadas a input()).
    Sondea la carpeta de Descargas durante DOWNLOAD_WAIT_TIME segundos y mueve los archivos a Entrada/.
    """
    rpa.show_pre_start_notification(rpa.NOTIFICATION_COUNTDOWN_SECONDS)
    print("\n" + "=" * 50)
    print("              1. FASE DE DESCARGA DE CSV (WEB)")
    print("=" * 50)

    config_params = rpa.load_config_parameters()
    max_age_seconds = config_params.get("max_download_age_seconds", 300)

    # Limpieza preventiva en Entrada/
    delete_unprocessed_input_files(rpa.ENTRADA_DIR, ["incident.csv", "sc_req_item.csv"])

    download_errors = []
    wait_timeout = max(float(rpa.DOWNLOAD_WAIT_TIME), 5.0)

    if download_incidents:
        inc_start = time.time()
        effective_min_mtime = min_mtime if min_mtime is not None else inc_start
        default_incident = (
            f"{rpa.SERVICENOW_BASE_URL}/incident_list.do?sysparm_query="
            f"assignment_group=e6313131f874ee55056b262c30cbb3551^OR"
            f"assignment_group=36ea16e087548210f2e1cbf80cbb35fd^"
            f"assigned_toISEMPTY^stateIN1,2&CSV"
        )
        incident_url = rpa.resolve_url(config_params.get("incident_download_url"), default_incident)
        print(f"Abriendo lista de incidentes en navegador: {incident_url}")
        rpa.open_url_in_browser(incident_url)
        print(f"Esperando hasta {wait_timeout}s para que se descargue el archivo de Incidentes...")

        moved = rpa.move_latest_download(
            "*incident*.csv",
            "incident.csv",
            min_mtime=effective_min_mtime,
            max_age_seconds=max_age_seconds,
            timeout_seconds=wait_timeout
        )
        dest_inc = os.path.join(rpa.ENTRADA_DIR, "incident.csv")
        fresh, reason = check_file_freshness(dest_inc, min_mtime=effective_min_mtime, max_age_seconds=max_age_seconds)
        if not moved or not fresh:
            err = f"Descarga fallida o inválida para Incidentes ({dest_inc}): {reason if not fresh else 'No se pudo mover el archivo reciente'}"
            print(f"[ERROR] {err}")
            download_errors.append(err)

    if download_requirements:
        req_start = time.time()
        effective_min_mtime = min_mtime if min_mtime is not None else req_start
        default_req = (
            f"{rpa.SERVICENOW_BASE_URL}/sc_req_item_list.do?sysparm_query="
            f"assignment_group=36ea16e087548210f2e1cbf80cbb35fd^OR"
            f"assignment_group=e6313131f874ee55056b262c30cbb3551^"
            f"state=1^assigned_toISEMPTY&CSV"
        )
        req_url = rpa.resolve_url(config_params.get("requirement_download_url"), default_req)
        print(f"\nAbriendo lista de requerimientos en navegador: {req_url}")
        rpa.open_url_in_browser(req_url)
        print(f"Esperando hasta {wait_timeout}s para que se descargue el archivo de Requerimientos...")

        moved = rpa.move_latest_download(
            "*sc_req_item*.csv",
            "sc_req_item.csv",
            min_mtime=effective_min_mtime,
            max_age_seconds=max_age_seconds,
            timeout_seconds=wait_timeout
        )
        dest_req = os.path.join(rpa.ENTRADA_DIR, "sc_req_item.csv")
        fresh, reason = check_file_freshness(dest_req, min_mtime=effective_min_mtime, max_age_seconds=max_age_seconds)
        if not moved or not fresh:
            err = f"Descarga fallida o inválida para Requerimientos ({dest_req}): {reason if not fresh else 'No se pudo mover el archivo reciente'}"
            print(f"[ERROR] {err}")
            download_errors.append(err)

    if download_errors:
        full_err_msg = " | ".join(download_errors)
        raise RuntimeError(f"Falla en la fase de descarga de ServiceNow: {full_err_msg}")


def web_close_browser_at_end():
    """
    Cierra la ventana del navegador abierta durante el ciclo esperando CLOSE_BROWSER_WAIT_TIME segundos
    para que todo se asiente, garantizando su cierre incluso si ocurrió un error.
    """
    if not getattr(rpa, "_browser_window_opened", False):
        return

    if getattr(rpa, "CLOSE_BROWSER_AT_END", True):
        wait_time = float(getattr(rpa, "CLOSE_BROWSER_WAIT_TIME", 10.0))
        print(f"\n[FINAL DE CICLO] Esperando {wait_time:.1f} segundos para que todo se asiente antes de cerrar el navegador (Alt+F4)...")
        time.sleep(wait_time)
        print("[FINAL DE CICLO] Cerrando ventana del navegador con Alt+F4...")
        try:
            rpa.pyautogui.hotkey('alt', 'f4')
        except Exception as e:
            print(f"[ADVERTENCIA] No se pudo enviar Alt+F4: {e}")
        time.sleep(1.0)
        rpa._browser_window_opened = False


# Sustituir la función de descarga y cierre de rpa por las versiones web
rpa.run_downloads = web_run_downloads
rpa.close_browser_at_end = web_close_browser_at_end


def run_action_solo_ia():
    """Ejecuta únicamente la inferencia de modelos IA sin interacción con ServiceNow."""
    with ExecutionLogger(rpa.SALIDA_DIR, prefix="ejecucion_inferencia_completa"):
        print("==================================================")
        print("        1. ASIGNACIÓN DE INCIDENTES (MODELOS IA)")
        print("==================================================")
        rpa.run_subprocess_logged([sys.executable, "Assigner_Incidents.py"])
        print("\n==================================================")
        print("        2. ASIGNACIÓN DE REQUERIMIENTOS (MODELOS IA)")
        print("==================================================")
        rpa.run_subprocess_logged([sys.executable, "Assigner_Requirements.py"])


def run_action_incidentes_completo():
    """Opción 1: Predicciones y Actualización DOM de Incidentes."""
    with ExecutionLogger(rpa.SALIDA_DIR, prefix="ejecucion_dom_incidentes"):
        rpa.reset_notification_state()
        try:
            cycle_start = time.time()
            if not rpa.SKIP_DOWNLOAD:
                web_run_downloads(download_incidents=True, download_requirements=False, min_mtime=cycle_start)
            else:
                print("\nOmitiendo fase de descarga (SKIP_DOWNLOAD=True). Usando CSVs locales en Entrada/.")
            rpa.run_predictions(run_incidents=True, run_requirements=False)
            inc_csv = rpa.find_latest_output_file("incidentes_con_asignacion_*.csv", min_mtime=cycle_start if not rpa.SKIP_DOWNLOAD else None)
            processed_inc = []
            if inc_csv:
                processed_inc = rpa.update_tickets_in_servicenow_dom(inc_csv, is_requirement=False) or []
            else:
                print("No se encontró archivo de salida de predicción para Incidentes.")
            rpa.verify_and_reassign_tickets(processed_incidents=processed_inc, processed_requirements=[])
        finally:
            web_close_browser_at_end()


def run_action_incidentes_dom():
    """Opción 2: Solo Actualizar DOM de Incidentes usando última predicción."""
    with ExecutionLogger(rpa.SALIDA_DIR, prefix="ejecucion_dom_incidentes"):
        rpa.reset_notification_state()
        print("\n--- Procesando únicamente Incidentes (Solo DOM) ---")
        try:
            inc_csv = rpa.find_latest_output_file("incidentes_con_asignacion_*.csv")
            processed_inc = []
            if inc_csv:
                processed_inc = rpa.update_tickets_in_servicenow_dom(inc_csv, is_requirement=False) or []
            else:
                print("No se encontró archivo de salida de predicción para Incidentes.")
            rpa.verify_and_reassign_tickets(processed_incidents=processed_inc, processed_requirements=[])
        finally:
            web_close_browser_at_end()


def run_action_requerimientos_completo():
    """Opción 3: Predicciones y Actualización DOM de Requerimientos."""
    with ExecutionLogger(rpa.SALIDA_DIR, prefix="ejecucion_dom_requerimientos"):
        rpa.reset_notification_state()
        try:
            cycle_start = time.time()
            if not rpa.SKIP_DOWNLOAD:
                web_run_downloads(download_incidents=False, download_requirements=True, min_mtime=cycle_start)
            else:
                print("\nOmitiendo fase de descarga (SKIP_DOWNLOAD=True). Usando CSVs locales en Entrada/.")
            rpa.run_predictions(run_incidents=False, run_requirements=True)
            req_csv = rpa.find_latest_output_file("requerimientos_con_asignacion_*.csv", min_mtime=cycle_start if not rpa.SKIP_DOWNLOAD else None)
            processed_req = []
            if req_csv:
                processed_req = rpa.update_tickets_in_servicenow_dom(req_csv, is_requirement=True) or []
            else:
                print("No se encontró archivo de salida de predicción para Requerimientos.")
            rpa.verify_and_reassign_tickets(processed_incidents=[], processed_requirements=processed_req)
        finally:
            web_close_browser_at_end()


def run_action_requerimientos_dom():
    """Opción 4: Solo Actualizar DOM de Requerimientos usando última predicción."""
    with ExecutionLogger(rpa.SALIDA_DIR, prefix="ejecucion_dom_requerimientos"):
        rpa.reset_notification_state()
        print("\n--- Procesando únicamente Requerimientos (Solo DOM) ---")
        try:
            req_csv = rpa.find_latest_output_file("requerimientos_con_asignacion_*.csv")
            processed_req = []
            if req_csv:
                processed_req = rpa.update_tickets_in_servicenow_dom(req_csv, is_requirement=True) or []
            else:
                print("No se encontró archivo de salida de predicción para Requerimientos.")
            rpa.verify_and_reassign_tickets(processed_incidents=[], processed_requirements=processed_req)
        finally:
            web_close_browser_at_end()


def run_action_completo():
    """Opción 5: Ejecución Completa (Incidentes + Requerimientos E2E)."""
    with ExecutionLogger(rpa.SALIDA_DIR, prefix="ejecucion_dom_completa"):
        try:
            rpa.run_rpa_loop()
        finally:
            web_close_browser_at_end()


def run_action_periodico(interval_mins=30.0):
    """Opción 6: Ciclo Completo Periódico Continuo."""
    interval_secs = int(interval_mins * 60)
    config_params = rpa.load_config_parameters()
    max_failures = config_params.get("max_consecutive_download_failures", 3)
    consecutive_failures = 0

    print("\n" + "=" * 50)
    print(f"Modo Periódico activado desde Panel Web!")
    print(f"Intervalo: {interval_mins} min ({interval_secs}s)")
    print(f"Límite de fallos consecutivos antes de detención: {max_failures}")
    print(f"Configuración: SKIP_DOWNLOAD={rpa.SKIP_DOWNLOAD}, DRY_RUN={rpa.DRY_RUN}")
    print("=" * 50 + "\n")

    with ExecutionLogger(rpa.SALIDA_DIR, prefix="ejecucion_dom_periodica") as logger:
        while True:
            cycle_start = time.time()
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"\n[{current_time}] Iniciando ciclo periódico...")

            try:
                rpa.run_rpa_loop(min_mtime=cycle_start)
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Ciclo finalizado exitosamente.")
                consecutive_failures = 0
            except KeyboardInterrupt:
                print("\nAutomatización detenida. Saliendo del ciclo.")
                break
            except Exception as e:
                consecutive_failures += 1
                print(f"\n[ERROR] Ocurrió una excepción en el ciclo periódico: {e}")
                print(f"[CONTROL] Intentos fallidos consecutivos: {consecutive_failures} de {max_failures}")
                if consecutive_failures >= max_failures:
                    print("\n" + "!" * 60)
                    print(f"[DETENCIÓN CRÍTICA] Se alcanzó el límite de {max_failures} fallos consecutivos.")
                    print("!" * 60 + "\n")
                    break
            finally:
                web_close_browser_at_end()
                try:
                    from Programas.PipelineUtils import parse_log_summary, append_execution_summary
                    if logger and getattr(logger, "log_path", None) and os.path.exists(logger.log_path):
                        stats = parse_log_summary(logger.log_path)
                        stats["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        stats["tipo_ejecucion"] = "RPA_DOM"
                        stats["duracion_seg"] = round(time.time() - cycle_start, 2)
                        stats["archivo_log"] = os.path.basename(logger.log_path)
                        append_execution_summary(rpa.SALIDA_DIR, stats)
                except Exception:
                    pass

            next_run = (datetime.now() + timedelta(seconds=interval_secs)).strftime('%H:%M:%S')
            print(f"Esperando {interval_mins} minutos. Siguiente ejecución a las {next_run}...")

            sleep_left = interval_secs
            try:
                while sleep_left > 0:
                    time.sleep(min(5, sleep_left))
                    sleep_left -= 5
            except KeyboardInterrupt:
                print("\nAutomatización detenida por el usuario. Saliendo.")
                break


def run_action_limpiar_csv():
    """Opción 7: Limpieza y corrección de codificación de archivos CSV."""
    with ExecutionLogger(rpa.SALIDA_DIR, prefix="mantenimiento_limpieza_csv"):
        print("==================================================")
        print("  LIMPIEZA Y CORRECCIÓN DE ARCHIVOS CSV")
        print("==================================================")
        clean_all_input_csv_files(verbose=True)


def parse_args():
    parser = argparse.ArgumentParser(description="Controlador Web RPA ServiceNow DOM")
    parser.add_argument("--action", type=str, default="6",
                        help="Acción o número de opción: 1, 2, 3, 4, 5, 6, 7, 8 (o nombres correspondientes)")
    parser.add_argument("--download", dest="download", action="store_true", default=True,
                        help="Descargar CSVs frescos desde ServiceNow")
    parser.add_argument("--skip-download", dest="download", action="store_false",
                        help="Omitir descarga y usar archivos locales existentes")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", default=False,
                        help="Modo seguro (inyectar sin guardar en ServiceNow)")
    parser.add_argument("--no-dry-run", dest="dry_run", action="store_false",
                        help="Modo producción (guardar y asignar en ServiceNow)")
    parser.add_argument("--show-popup", dest="show_popup", action="store_true", default=True,
                        help="Mostrar ventana emergente de aviso")
    parser.add_argument("--no-popup", dest="show_popup", action="store_false",
                        help="Desactivar ventana emergente de aviso")
    parser.add_argument("--popup-seconds", type=int, default=5,
                        help="Segundos de cuenta regresiva para el popup")
    parser.add_argument("--download-wait", type=float, default=10.0,
                        help="Segundos de espera para descargas desde el navegador")
    parser.add_argument("--load-time", type=float, default=10.0,
                        help="Segundos de espera para carga de página en ServiceNow")
    parser.add_argument("--clipboard-time", type=float, default=1.0,
                        help="Segundos de pausa tras interactuar con portapapeles")
    parser.add_argument("--interval-mins", type=float, default=30.0,
                        help="Intervalo en minutos para modo periódico")
    parser.add_argument("--verification-wait", type=float, default=30.0,
                        help="Segundos de espera para asentamiento en ServiceNow antes de verificar persistencia")
    parser.add_argument("--close-browser-wait", type=float, default=10.0,
                        help="Segundos de espera para que todo se asiente antes de cerrar el navegador al final")
    return parser.parse_args()


def main():
    args = parse_args()

    # Inyectar parámetros en el módulo rpa
    rpa.SKIP_DOWNLOAD = not args.download
    rpa.DRY_RUN = bool(args.dry_run)
    rpa.SHOW_NOTIFICATION_POPUP = bool(args.show_popup)
    rpa.NOTIFICATION_COUNTDOWN_SECONDS = int(args.popup_seconds)
    rpa.DOWNLOAD_WAIT_TIME = float(args.download_wait)
    rpa.LOAD_TIME = float(args.load_time)
    rpa.CLIPBOARD_TIME = float(args.clipboard_time)
    rpa.VERIFICATION_WAIT_TIME = float(args.verification_wait)
    rpa.CLOSE_BROWSER_WAIT_TIME = float(args.close_browser_wait)

    # Imprimir cabecera de ejecución web
    print("=" * 60)
    print("      RPA SERVICENOW DOM - CONTROLADOR WEB DESATENDIDO")
    print("=" * 60)
    print(f" Acción seleccionada           : {args.action}")
    print(f" Descargar desde ServiceNow     : {'SÍ (Descarga en vivo)' if args.download else 'NO (Usa CSVs locales en Entrada/)'}")
    print(f" Modo de Guardado (DRY_RUN)    : {'Simulación (no guarda en ServiceNow)' if args.dry_run else 'Guardado directo en Producción'}")
    print(f" Notificación Emergente         : {'Activa (' + str(args.popup_seconds) + 's)' if args.show_popup else 'Desactivada'}")
    print(f" Tiempos de Interacción         : Descarga={args.download_wait}s | Carga={args.load_time}s | Clipboard={args.clipboard_time}s")
    print(f" Asentamiento y Cierre          : Asentamiento SN={args.verification_wait}s | Cierre Navegador={args.close_browser_wait}s")
    if args.action in ("6", "periodico"):
        print(f" Intervalo Periódico            : {args.interval_mins} minutos")
    print("=" * 60 + "\n")

    action = str(args.action).lower().strip()

    if action in ("1", "incidentes_completo"):
        run_action_incidentes_completo()
    elif action in ("2", "incidentes_dom"):
        run_action_incidentes_dom()
    elif action in ("3", "requerimientos_completo"):
        run_action_requerimientos_completo()
    elif action in ("4", "requerimientos_dom"):
        run_action_requerimientos_dom()
    elif action in ("5", "completo", "rpa_full"):
        run_action_completo()
    elif action in ("6", "periodico"):
        run_action_periodico(args.interval_mins)
    elif action in ("7", "limpiar_csv", "limpieza"):
        run_action_limpiar_csv()
    elif action in ("8", "solo_ia", "ml_only"):
        run_action_solo_ia()
    else:
        print(f"[ERROR] Acción desconocida: '{args.action}'. Opciones válidas: 1 a 8.")
        sys.exit(1)


if __name__ == "__main__":
    main()
