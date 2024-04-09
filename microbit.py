from microbit import *
import music

class MicrobitDisplay:
    def __init__(self):
        self.animation_sequences = {
            'NORMAL': [(Image.HEART, 1000), (Image.HEART_SMALL, 1000)],
            'CHEAP': [(Image.HAPPY, 500)],
            'VERY_CHEAP': [(Image.YES, 500)],
            'EXPENSIVE': [(Image.TRIANGLE, 500)],
            'VERY_EXPENSIVE': [(Image.NO, 500)]
        }
        self.price_level = "Unknown"
        self.valid_from = "00:00"
        self.total_price = "0.0"
        uart.init(baudrate=115200)

    def animate_price_level(self):
        sequence = self.animation_sequences.get(self.price_level, [(Image.CONFUSED, 1000)])
        for image, delay in sequence:
            display.show(image)
            sleep(delay)

    def update_display(self):
        if uart.any():
            data = uart.readline().decode('utf-8').rstrip()
            if data == "TERMINATE":
                self.price_level = "Unknown"
                self.valid_from = "00:00"
                self.total_price = "0.0"
                display.show(Image.CONFUSED)
                return

            try:
                new_price_level, self.valid_from, self.total_price = data.split(',')
                self.price_level = new_price_level
                display.clear()
            except ValueError:
                display.show(Image.SAD)
                sleep(1000)
                display.clear()

        if button_a.is_pressed() and button_b.is_pressed():
            display.scroll("Time: " + self.valid_from + " Price: " + self.total_price, delay=100)
        elif button_a.is_pressed():
            display.scroll(self.price_level, delay=100)
        elif button_b.is_pressed():
            display.scroll(self.total_price, delay=100)
        else:
            self.animate_price_level()

microbit_display = MicrobitDisplay()

while True:
    microbit_display.update_display()
