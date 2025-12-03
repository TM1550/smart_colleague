import subprocess
import time
import sys
import os

def run_service(service_name, port):
    """Запуск микросервиса"""
    print(f"Starting {service_name} on port {port}...")
    env = os.environ.copy()
    env['PYTHONPATH'] = os.getcwd()
    
    process = subprocess.Popen([
        sys.executable, f"{service_name}.py"
    ], env=env)
    
    return process

def main():
    services = [
        ("auth_service", 8001),
        ("site_service", 8002),
        ("analysis_service", 8003),
        ("instruction_service", 8004),
        ("chat_service", 8005),
        ("api_gateway", 5000)
    ]
    
    processes = []
    
    try:
        # Запускаем все сервисы
        for service_name, port in services:
            process = run_service(service_name, port)
            processes.append(process)
            time.sleep(2)  # Даем время для запуска
        
        print("\nAll services started! Press Ctrl+C to stop.")
        
        # Ждем завершения
        for process in processes:
            process.wait()
            
    except KeyboardInterrupt:
        print("\nStopping all services...")
        for process in processes:
            process.terminate()
        for process in processes:
            process.wait()
        print("All services stopped.")

if __name__ == "__main__":
    main()