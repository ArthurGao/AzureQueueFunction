import logging

import azure.functions as func


import io
import json
import os
import azure.functions as func
import pandas as pd
from azure.storage.blob import BlobServiceClient
from neuralprophet import NeuralProphet
import asyncio
import datetime
from azure.storage.blob import ContentSettings
import logging 
import tempfile


def generate_y_forecast(df: pd.DataFrame, freq: str, forecast_periods: int, 
                        historic_predictions: bool = True,
                        epochs: int = None):
    logging.info("generate_y_forecast start")
    tempFilePath = tempfile.gettempdir()
    os.chdir(tempFilePath)
    logging.info(tempFilePath)

    # Initialize NeuralProphet model and fit data
    neural_prophet = NeuralProphet(n_forecasts=forecast_periods, collect_metrics=True, epochs=epochs)
    metrics = neural_prophet.fit(df, freq=freq)
    logging.info("generate_y_forecast fit done")
    # Make future dataframe and forecast
    future = neural_prophet.make_future_dataframe(df, periods=forecast_periods, n_historic_predictions=historic_predictions)
    forecast = neural_prophet.predict(future).round(2)
    logging.info("generate_y_forecast done")
    return forecast.round(2)


def create_and_upload_blob(blob_service_client, result_json_blob_name, forecast_data):
    logging.info("create_and_upload_blob start")
    forecast_data['ds'] = forecast_data['ds'].dt.strftime('%Y-%m-%d %H:%M:%S')
    json_data = json.dumps(forecast_data.to_dict(orient='split'))
    
    logging.info(f"Adding json data to blob {json_data}")
    with open(result_json_blob_name, "w") as json_file:
        json_file.write(json_data)
    
    upload_blob_client = blob_service_client.get_blob_client(container=os.environ['container_name'], blob=result_json_blob_name)
    with open(result_json_blob_name, "rb") as data:
        content_settings = ContentSettings(content_type='application/json')
        upload_blob_client.upload_blob(data, overwrite=True, content_settings=content_settings)
    logging.info("create_and_upload_blob end")

        
def execute_forecast(df, freq, forecast_periods, historic_predictions, epochs, blob_service_client, result_csv_blob_name):
    logging.info("execute_forecast start")
    forecast = generate_y_forecast(df, freq, forecast_periods, historic_predictions, epochs)
    current_time = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    # Append the timestamp to the result_csv_blob_name
    result_json_blob_name_with_time = result_csv_blob_name + '_' + current_time + ".json"
    create_and_upload_blob(blob_service_client, result_json_blob_name_with_time, forecast)
    logging.info("execute_forecast end")


def main(msg: func.QueueMessage) -> None:
    try:
        req_body = json.loads(msg.get_body().decode('utf-8'))
        #req_body = req.get_json()
        input_csv_blob_name = req_body.get('input_csv_name')
        result_csv_blob_name = req_body.get('result_json_name')

        forecast_periods = req_body.get('forecast_periods', 365 * 3)
        historic_predictions = req_body.get('historic_predictions', True)
        epochs = req_body.get('epochs', None)
        freq = req_body.get('freq', 'D')

        # Connect to your Azure Blob Storage account
        blob_service_client = BlobServiceClient.from_connection_string(os.environ['AzureWebJobsStorage'])
        download_blob_client = blob_service_client.get_blob_client(container=os.environ['container_name'], blob=input_csv_blob_name)

        # Download the CSV file from Blob Storage
        csv_data = download_blob_client.download_blob()
        csv_text = csv_data.content_as_text(encoding='utf-8')
        df = pd.read_csv(io.StringIO(csv_text))
        df['ds'] = pd.to_datetime(df['ds'])
        execute_forecast(df, freq, forecast_periods, historic_predictions, epochs, blob_service_client, result_csv_blob_name)

    except Exception as e:
        return func.HttpResponse(f"An error occurred: {str(e)}", status_code=500)

