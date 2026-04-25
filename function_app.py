import logging

import azure.functions as func

from stock_notifier import load_monitors, run_check


app = func.FunctionApp()


@app.function_name(name="stock_timer")
@app.timer_trigger(
    schedule="0 */15 * * * *",
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True,
)
def stock_timer(timer: func.TimerRequest) -> None:
    if timer.past_due:
        logging.info("Stock timer is running later than scheduled.")

    monitors = load_monitors()
    logging.info("Checking %s stock monitor(s).", len(monitors))
    run_check(monitors, send_notifications=True)
