import sys
import subprocess
import os

def train_incident_models():
    """Train supervised and unsupervised models for incidents"""
    print("Training incident models...")
    
    # Change to incident directory and run training
    original_cwd = os.getcwd()
    try:
        os.chdir("../Incidentes")
        
        # Train supervised model
        print("Training supervised incident model...")
        subprocess.run([sys.executable, "SupervisedMultipleFeatureIncidents.py"], check=True)
        
        # Train unsupervised model
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
        os.chdir("../Requerimientos")
        
        # Train supervised model
        print("Training supervised requirement model...")
        subprocess.run([sys.executable, "SupervisedMultipleFeatureRequirements.py"], check=True)
        
        # Train unsupervised model
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
