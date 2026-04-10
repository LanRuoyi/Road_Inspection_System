@echo off

REM Navigate to backend and start the backend server
cd backend || (echo Failed to navigate to backend folder & pause & exit)
conda activate road || (echo Failed to activate Conda environment & pause & exit)
python scripts\dev_server.py --host 0.0.0.0 --port 8001 --reload || (echo Failed to start backend server & pause & exit)

REM Navigate to frontend and start the frontend server
cd ../frontend || (echo Failed to navigate to frontend folder & pause & exit)
npm run dev || (echo Failed to start frontend server & pause & exit)

Pause