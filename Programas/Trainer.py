import sys
import subprocess
import os

def train_incident_models():
    """Train supervised and unsupervised models for incidents"""
    print("Training incident models...")
    
    original_cwd = os.getcwd()
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Train supervised model
        supervised_dir = os.path.normpath(os.path.join(script_dir, "..", "Incidentes", "Entrenamiento", "Supervisado"))
        print(f"Changing directory to: {supervised_dir}")
        os.chdir(supervised_dir)
        print("Training supervised incident model...")
        subprocess.run([sys.executable, "SupervisedMultipleFeatureIncidents.py"], check=True)
        
        # Train unsupervised model
        unsupervised_dir = os.path.normpath(os.path.join(script_dir, "..", "Incidentes", "Entrenamiento", "No supervisado"))
        print(f"Changing directory to: {unsupervised_dir}")
        os.chdir(unsupervised_dir)
        print("Training unsupervised incident model...")
        subprocess.run([sys.executable, "UnsupervisedMultipleFeatureIncidents.py"], check=True)
        
    except subprocess.CalledProcessError as e:
        print(f"Error training incident models: {e}")
        raise
    finally:
        os.chdir(original_cwd)

def train_requirement_models():
    """Train supervised and unsupervised models for requirements"""
    print("Training requirement models...")
    
    original_cwd = os.getcwd()
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Train supervised model
        supervised_dir = os.path.normpath(os.path.join(script_dir, "..", "Requerimientos", "Entrenamiento", "Supervisado"))
        print(f"Changing directory to: {supervised_dir}")
        os.chdir(supervised_dir)
        print("Training supervised requirement model...")
        subprocess.run([sys.executable, "SupervisedMultipleFeatureRequirements.py"], check=True)
        
        # Train unsupervised model
        unsupervised_dir = os.path.normpath(os.path.join(script_dir, "..", "Requerimientos", "Entrenamiento", "No supervisado"))
        print(f"Changing directory to: {unsupervised_dir}")
        os.chdir(unsupervised_dir)
        print("Training unsupervised requirement model...")
        subprocess.run([sys.executable, "UnsupervisedMultipleFeatureRequirements.py"], check=True)
        
    except subprocess.CalledProcessError as e:
        print(f"Error training requirement models: {e}")
        raise
    finally:
        os.chdir(original_cwd)

def train_all_models():
    """Train all ML models - call this when you need to update models"""
    print("Training all ML models...")
    try:
        train_incident_models()
        train_requirement_models()
        print("Model training completed successfully")
    except Exception as e:
        print(f"Model training failed: {e}")
        raise

if __name__ == "__main__":
    train_all_models()

