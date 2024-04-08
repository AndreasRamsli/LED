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
    
    def check_for_interrupt(self):
        return uart.any() or button_a.is_pressed() or button_b.is_pressed()

    def animate_price_level(self):
        sequence = self.animation_sequences.get(self.price_level, [(Image.CONFUSED, 1000)])
        while not self.check_for_interrupt():
            for image, delay in sequence:
                display.show(image)
                sleep(delay)
                if self.check_for_interrupt():
                    return
    
    def update_display(self):
        if uart.any():
            try:
                data = uart.readline().decode('utf-8').rstrip()
                new_price_level, self.valid_from, self.total_price = data.split(',')
                display.clear()
                
                old_level_priority = self.get_price_level_priority(self.price_level)
                new_level_priority = self.get_price_level_priority(new_price_level)
                
                if new_price_level != self.price_level:
                    # Determine the direction of the price level change
                    if new_level_priority > old_level_priority:
                        # Moving up: Play a rising tone
                        music.play(music.POWER_UP)
                    elif new_level_priority < old_level_priority:
                        # Moving down: Play a falling tone
                        music.play(music.POWER_DOWN)
                    else:
                        # No change in level or unknown, optional: play a neutral sound
                        pass
                    
                    self.price_level = new_price_level

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
            
    def get_price_level_priority(self, price_level):
        priority = {
            'VERY_CHEAP': 0,
            'CHEAP': 1,
            'NORMAL': 2,
            'EXPENSIVE': 3,
            'VERY_EXPENSIVE': 4
        }
        return priority.get(price_level, -1)  # Unknown or any other level defaults to -1


microbit_display = MicrobitDisplay()

while True:
    microbit_display.update_display()
