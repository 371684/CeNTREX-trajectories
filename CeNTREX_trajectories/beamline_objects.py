import pickle
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List, Optional, Union

import numpy as np
import numpy.typing as npt

from .data_structures import Coordinates, Force
from .propagation import PropagationType
from .particles import Particle

__all__ = [
    "Section",
    "ElectrostaticQuadrupoleLens",
    "MagnetostaticHexapoleLens",
    "CircularAperture",
    "RectangularAperture",
]

path = Path(__file__).resolve().parent
with open(path / "saved_data" / "stark_poly.pkl", "rb") as f:
    stark_poly = pickle.load(f)
    stark_potential = np.poly1d(stark_poly)
    stark_potential_derivative = np.polyder(stark_potential)


@dataclass
class Section:
    """
    Generic Section dataclass

    Attributes:
        name (str): name of section
        objects (List): objects inside the section which particles can collide with
        start (float): start of section in z [m]
        stop (float): end of section in z [m]
        save_collisions (bool): save the coordinates and velocities of collisions in
                                this section
        propagation_type (PropagationType): propagation type to use for integration
        force (Optional([Union[Callable, Force]]): force to use, either a function that
                                                calculates the force based on t,x,y,z
                                                or a constant force

    """

    name: str
    objects: List[Any]
    start: float
    stop: float
    save_collisions: bool
    propagation_type: PropagationType
    force: Optional[Union[Callable, Force]] = None

    def __post_init__(self):
        """
        Check if all objects reside fully inside the section, runs upon initialization.
        """
        for o in self.objects:
            assert o.check_in_bounds(
                self.start, self.stop
            ), f"{o.name} not inside {self.name}"


class ODESection:
    propagation_type: PropagationType = PropagationType.ode

    def _check_objects(self):
        """
        Check if all objects reside fully inside the section, runs upon initializatin.
        """
        for o in self.objects:
            assert o.check_in_bounds(
                self.start, self.stop
            ), f"{o.name} not inside {self.name}"

    def force(self, x, y, z) -> Union[List[float], List[npt.NDArray[np.float64]]]:
        raise NotImplementedError


class ElectrostaticQuadrupoleLens(ODESection):
    """
    Electrostatic Quadrupole Lens class
    """

    def __init__(
        self,
        name: str,
        objects: List[Any],
        start: float,
        stop: float,
        V: float,
        R: float,
        save_collisions: Optional[bool] = False,
    ) -> None:
        """
        Electrostatic Quadrupole Lens Section

        Args:
            name (str): name of electrostatic quadrupole lens
            objects (List): objects inside the section which particles can collide with
            start (float): start of section in z [m]
            stop (float): stop of section in z [m]
            V (float): Voltage on electrodes [Volts]
            R (float): radius of lens bore [m]
            save_collisions (Optional[bool], optional): Save the coordinates and
                                                    velocities of collisions in this
                                                    section. Defaults to False.
        """
        self.name = name
        self.objects = objects
        self.start = start
        self.stop = stop
        self.V = V
        self.R = R
        self.save_collisions = save_collisions
        self._check_objects()
        self._initialize_potentials()

    def _initialize_potentials(self):
        """
        Generate the radial derivative of the Stark potential for the force calculation
        """
        # fit a polynomial to the stark potential as a fucntion of r
        r = np.linspace(0, 1.5 * self.R, 201)
        offset = self.stark_potential(0, 0, 0)
        self._poly_stark_radial = np.polyfit(
            r, self.stark_potential(r, 0, 0) - offset, 11
        )
        # take the derivative
        self._poly_stark_derivative_radial = np.polyder(
            np.poly1d(self._poly_stark_radial)
        )
        # force intercept to go through zero for the force by fitting a polynomial
        # that intercepts zero through the derivative as a function of r
        R_ = np.vstack((r ** 6, r ** 5, r ** 4, r ** 3, r ** 2, r)).T
        y = self._poly_stark_derivative_radial(r)
        p = np.linalg.lstsq(R_, y, rcond=None)[0]
        p = np.append(p, [0])
        # creating the function to evaluate the derivative of the stark potential in r
        self._poly_stark_derivative_radial = np.poly1d(p)

    def electric_field(
        self,
        x: Union[npt.NDArray[np.float64], float],
        y: Union[npt.NDArray[np.float64], float],
        z: Union[npt.NDArray[np.float64], float],
    ) -> Union[npt.NDArray[np.float64], float]:
        """
        Calculate the electric field of the lens at x,y,z

        Args:
            x (Union[NDArray[np.float64], float]): x coordinate(s) [m]
            y (Union[NDArray[np.float64], float]): y coordinate(s) [m]
            z (Union[NDArray[np.float64], float]): z coordinate(s) [m]

        Returns:
            Union[NDArray[np.float64], float]: electric field at x,y,z in V/m
        """
        return 2 * self.V * np.sqrt(x ** 2 + y ** 2) / (self.R) ** 2

    def force(
        self,
        x: Union[npt.NDArray[np.float64], float],
        y: Union[npt.NDArray[np.float64], float],
        z: Union[npt.NDArray[np.float64], float],
    ) -> Union[List[npt.NDArray[np.float64]], List[float]]:
        """
        Calculate the force at x,y,z

        Args:
            x (Union[NDArray[np.float64], float]): x coordinate(s) [m]
            y (Union[NDArray[np.float64], float]): y coordinate(s) [m]
            z (Union[NDArray[np.float64], float]): z coordinate(s) [m]

        Returns:
            List: force in x, y and z
        """
        r = np.sqrt(x ** 2 + y ** 2)
        dx = x / r
        dy = y / r
        stark = -self._poly_stark_derivative_radial(r)
        return [stark * dx, stark * dy, 0]

    def stark_potential_derivative(
        self,
        x: Union[npt.NDArray[np.float64], float],
        y: Union[npt.NDArray[np.float64], float],
        z: Union[npt.NDArray[np.float64], float],
    ) -> Union[npt.NDArray[np.float64], float]:
        """
        Calculate the radial derivative of the stark potential at x,y,z

        Args:
            x (Union[NDArray[np.float64], float]): x coordinate(s) [m]
            y (Union[NDArray[np.float64], float]): y coordinate(s) [m]
            z (Union[NDArray[np.float64], float]): z coordinate(s) [m]

        Returns:
            Union[np.ndarray, float]: radial derivative of stark potential
        """
        return self._poly_stark_derivative_radial(np.sqrt(x ** 2 + y ** 2))

    def stark_potential(
        self,
        x: Union[npt.NDArray[np.float64], float],
        y: Union[npt.NDArray[np.float64], float],
        z: Union[npt.NDArray[np.float64], float],
    ) -> Union[npt.NDArray[np.float64], float]:
        """
        Calculate the the stark potential at x,y,z

        Args:
            x (Union[NDArray[np.float64], float]): x coordinate(s) [m]
            y (Union[NDArray[np.float64], float]): y coordinate(s) [m]
            z (Union[NDArray[np.float64], float]): z coordinate(s) [m]

        Returns:
            Union[NDArray[np.float64], float]: stark potential
        """
        E = self.electric_field(x, y, z)
        return stark_potential(E)

    def stark_potential_E(
        self, E: Union[npt.NDArray[np.float64], float]
    ) -> Union[npt.NDArray[np.float64], float]:
        """
        Calculate the stark potential as a function of electric field in V/m

        Args:
            E (Union[np.ndarray, float]): electric field in V/m

        Returns:
            Union[np.ndarray, float]: stark potential
        """
        return stark_potential(E)


class MagnetostaticHexapoleLens(ODESection):
    """
    Magnetic Hexapole Lens class

    The magnetic field can be expressed as:
        Br = Bar * cos(3ϕ) * (r/Rin)**2
        Bϕ = -Bar * sin(3ϕ) * (r/Rin)**2
        Bz = 0
    From Manipulating beams of paramagnetic atoms and molecules using
    inhomogeneous magnetic fields (Progress in Nuclear Magnetic Resonance Spectroscopy,
    Volumes 120-121, https://doi.org/10.1016/j.pnmrs.2020.08.002)
    where Bar is given by:
        B0 * (n/(n-1)) * cos(π/M)**n * sin(2π/M)/(nπ/M) * (1-(Rin/Rout)**(n-1))
        if n > 1 or
        B0 * sin(2π/M)/(2π/M) * ln(Rout/Rin)
        if n = 1
    Here n is a measure for how many poles (Hexapole has n=3), M is the number of
    magnet sections, Rin is the inner radius, Rout the outer radius and B0 is a constant
    scaling the magnetic field.
    Expression from Eq 5 a/b from Application of permanent magnets in accelerators
    and electron storage rings (Journal of Applied Physics 57, 3605 (1985)).
    https://doi.org/10.1063/1.335021

    Converting to cartesian coordinates:
        r = sqrt(x**2 + y**2)
        ϕ = arctan2(y,x)
        sin(ϕ) = y/r
        cos(ϕ) = x/r
        sin(3ϕ) = 3*sin(ϕ)*cos(ϕ)**2 - sin(ϕ)**3
        cos(3ϕ) = cos(ϕ)**3 - 3*sin(ϕ)**2 * cos(ϕ)
        Bx = cos(ϕ)*Br - sin(ϕ)*Bϕ
        By = sin(ϕ)*Br + cos(ϕ)*Bϕ
        Bz = Bz

    Using sympy:
    ```Python
    import sympy as smp
    r, ϕ, Bar, Rin, x, y, μx, μy = smp.symbols("r ϕ Bar Rin x y μx μy")

    # substitutions
    subsine = [(smp.sin(ϕ), y/r), (smp.cos(ϕ), x/r)]
    subr = [(r, smp.sqrt(x**2 + y**2))]
    subsine3 = [
        (smp.sin(3*ϕ), 3*smp.sin(ϕ)*smp.cos(ϕ)**2 - smp.sin(ϕ)**3),
        (smp.cos(3*ϕ), smp.cos(ϕ)**3 - 3*smp.sin(ϕ)**2*smp.cos(ϕ))
    ]

    Br = Bar * smp.cos(3*ϕ) * (r/Rin)**2
    Bϕ = -Bar * smp.sin(3*ϕ) * (r/Rin)**2
    Bx = smp.cos(ϕ) * Br - smp.sin(ϕ)*Bϕ
    By = smp.sin(ϕ) * Br + smp.cos(ϕ)*Bϕ

    Bx = Bx.subs(subsine3 + subsine + subr).simplify()
    By = By.subs(subsine3 + subsine + subr).simplify()

    dBx = smp.sqrt(smp.diff(Bx,x)**2 + smp.diff(By,x)**2).simplify()
    dBy = smp.sqrt(smp.diff(Bx,y)**2 + smp.diff(By,y)**2).simplify()

    fx = (x/r * dBx).subs(subr).simplify() * -μx
    fy = (y/r * dBy).subs(subr).simplify() * -μy

    ```
    """

    def __init__(
        self,
        name: str,
        objects: List[Any],
        start: float,
        stop: float,
        particle: Particle,
        Rin: float,
        Rout: float,
        M: int,  # nr of blocks in the magnet
        n: int = 3,  # n = 2 -> quadrupole; n = 3 -> hexapole
        save_collisions: Optional[bool] = False,
    ) -> None:
        self.name = name
        self.objects = objects
        self.start = start
        self.stop = stop
        self.particle = particle

        self.Rin = Rin
        self.Rout = Rout
        self.n = n
        self.M = M
        self._magnetic_field_aperture_radius()

    def force(
        self,
        x: Union[npt.NDArray[np.float64], float],
        y: Union[npt.NDArray[np.float64], float],
        z: Union[npt.NDArray[np.float64], float],
    ) -> Union[List[npt.NDArray[np.float64]], List[float]]:
        """
        Calculate the force at x,y,z

        The magnetic force on the dipole is given by F = ∇(μ⋅B).

        Args:
            x (Union[NDArray[np.float64], float]): x coordinate(s) [m]
            y (Union[NDArray[np.float64], float]): y coordinate(s) [m]
            z (Union[NDArray[np.float64], float]): z coordinate(s) [m]

        Returns:
            List: force in x, y and z
        """
        # μ points in the direction of B for a sufficiently large field (e.g. in the
        # hexapole), so μ points along x/r, y/r, 0

        fx = -2 * x * self.Bar / self.Rin ** 2 * self.particle.magnetic_moment
        fy = -2 * y * self.Bar / self.Rin ** 2 * self.particle.magnetic_moment
        fz = fx * 0.0
        return [fx, fy, fz]

    def _magnetic_field_aperture_radius(self) -> None:
        """
        Expression from Eq 5 a/b from Application of permanent magnets in accelerators
        and electron storage rings (Journal of Applied Physics 57, 3605 (1985)).
        https://doi.org/10.1063/1.335021
        """
        Br = 1
        n, M = self.n, self.M
        Rin, Rout = self.Rin, self.Rout
        if self.n > 1:
            self.Bar = (
                Br
                * (n / (n - 1))
                * np.cos(np.pi / M) ** n
                * (np.sin(n * np.pi / M) / (n * np.pi / M))
                * (1 - (Rin / Rout) ** (n - 1))
            )
        elif self.n == 1:
            self.Bar = Br * np.sin(np.pi / M) / (2 * np.pi / M) * np.log(Rout / Rin)

    def magnetic_field_cylindrical(
        self,
        r: Union[npt.NDArray[np.float64], float],
        ϕ: Union[npt.NDArray[np.float64], float],
        z: Union[npt.NDArray[np.float64], float],
    ) -> Union[List[float], List[npt.NDArray[np.float64]]]:
        Br = self.Bar * np.cos(3 * ϕ) * (r / self.Rin) ** 2
        Bϕ = -self.Bar * np.sin(3 * ϕ) * (r / self.Rin) ** 2
        Bz = Br * 0.0
        return [Br, Bϕ, Bz]

    def magnetic_field_cartesian(
        self,
        x: Union[npt.NDArray[np.float64], float],
        y: Union[npt.NDArray[np.float64], float],
        z: Union[npt.NDArray[np.float64], float],
    ) -> Union[List[float], List[npt.NDArray[np.float64]]]:
        r = np.sqrt(x ** 2 + y ** 2)
        ϕ = np.arctan2(y, x)
        Br, Bϕ, Bz = self.magnetic_field_cylindrical(r, ϕ, z)
        Bx = np.cos(ϕ) * Br - np.sin(ϕ) * Bϕ
        By = np.sin(ϕ) * Br + np.cos(ϕ) * Bϕ
        Bz = Bx * 0.0
        return [Bx, By, Bz]


@dataclass
class Aperture:
    """
    Aperture base class

    Attributes:
        x (float): x coordinate [m]
        y (float): y coordinate [m]
        z (float): z coordinate [m]
    """

    x: float
    y: float
    z: float

    def check_in_bounds(self, start: float, stop: float) -> bool:
        """
        Check if the aperture is within the specified bounds

        Args:
            start (float): start coordinate in z [m]
            stop (float): stop coordinate in z [m]

        Returns:
            bool: True if within bounds, else False
        """
        return (self.z >= start) & (self.z <= stop)

    def get_acceptance(self, coords: Coordinates) -> npt.NDArray[np.bool_]:
        raise NotImplementedError

    def collision_event_function(self, x: float, y: float, z: float) -> float:
        raise NotImplementedError


@dataclass
class CircularAperture(Aperture):
    """
    Circular aperture

    Attributes:
        x (float): x coordinate [m]
        y (float): y coordinate [m]
        z (float): z coordinate [m]
        r (float): radius of the aperture [m]
    """

    r: float

    def get_acceptance(self, coords: Coordinates) -> npt.NDArray[np.bool_]:
        """
        check if the supplied coordinates are within the aperture

        Args:
            coords (Coordinates): coordinates to check

        Returns:
            np.ndarray: boolean array where True indicates coordinates are within the
            aperture
        """
        assert np.allclose(
            coords.z, self.z
        ), "supplied coordinates not at location of aperture"
        return (coords.x - self.x) ** 2 + (coords.y - self.y) ** 2 <= self.r ** 2

    def collision_event_function(self, x: float, y: float, z: float) -> float:
        return (x - self.x) + (y - self.y) + (z - self.z)


@dataclass
class RectangularAperture(Aperture):
    """
    Rectangular aperture

    Attributes:
        x (float): x coordinate [m]
        y (float): y coordinate [m]
        z (float): z coordinate [m]
        wx (float): width of the aperture [m]
        wy (float): height of the aperture [m]
    """

    wx: float
    wy: float

    def get_acceptance(self, coords: Coordinates) -> npt.NDArray[np.bool_]:
        """
        check if the supplied coordinates are within the aperture

        Args:
            coords (Coordinates): coordinates to check

        Returns:
            np.ndarray: boolean array where True indicates coordinates are within the
            aperture
        """
        assert np.allclose(
            coords.z, self.z
        ), "supplied coordinates not at location of aperture"
        return (np.abs((coords.x - self.x)) <= self.wx / 2) & (
            np.abs((coords.y - self.y)) <= self.wy / 2
        )

    def collision_event_function(self, x: float, y: float, z: float) -> float:
        x_factor = 0 if (x >= self.x - self.wx / 2 and x <= self.x + self.wx / 2) else 1
        y_factor = 0 if (y >= self.y - self.wy / 2 and y <= self.y + self.wy / 2) else 1
        return z - self.z + x_factor + y_factor


@dataclass
class PlateElectrodes:
    x: float
    y: float
    z: float
    length: float
    width: float

    def check_in_bounds(self, start: float, stop: float) -> bool:
        return self.z >= start and self.z + self.length <= stop

    def get_acceptance(self, coords: Coordinates) -> npt.NDArray[np.bool_]:
        return np.ones(coords.x.shape, dtype=np.bool_)

    def collision_event_function(self, x: float, y: float, z: float) -> float:
        # for now assume electrode plates in y direction

        # z_factor for checking if z coordinates are within electrodes
        z_factor = 0 if (z >= self.z and z <= self.z + self.length) else 1

        # y_factor for checking if z coordinates are within electrodes
        y_factor = (
            0 if (y >= self.y - self.width / 2 and y <= self.y + self.width / 2) else 1
        )
        return (x - self.x) + y_factor + z_factor


@dataclass
class Bore:
    x: float
    y: float
    z: float
    length: float
    radius: float

    def check_in_bounds(self, start: float, stop: float) -> bool:
        return self.z >= start and self.z + self.length <= stop

    def get_acceptance(self, coords: Coordinates) -> npt.NDArray[np.bool_]:
        mask_z = (coords.z >= self.z) & (coords.z <= self.z + self.length)
        mask_r = (
            (coords.x - self.x) ** 2 + (coords.y - self.y) ** 2
        ) > self.radius ** 2
        accept_array = np.ones(coords.x.shape, dtype=np.bool_)
        accept_array[mask_z & mask_r] = False
        return accept_array

    def collision_event_function(self, x: float, y: float, z: float) -> float:
        r_squared = np.sqrt((x - self.x) ** 2 + (y - self.y) ** 2)

        # z_factor for checking if z coordinates are within electrodes
        z_factor = 0 if (z >= self.z and z <= self.z + self.length) else 1
        return r_squared - self.radius + z_factor
